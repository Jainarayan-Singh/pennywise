"""WebAuthn registration and authentication using the maintained `webauthn` library.

No cryptography is implemented here. This module adds the application rules the
library cannot know: single-use expiring challenges bound to a user/browser
session, credential ownership, and persistence of signature counters.
"""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from flask import session
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, options_to_json_dict
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.config import Settings
from app.extensions import db
from app.models import AuthChallenge, PasskeyCredential, User
from app.models.base import utcnow
from app.services.audit_service import record_event
from app.utils.errors import ApiError

logger = logging.getLogger(__name__)

SESSION_KEY = "passkey_challenge_id"
PURPOSE_REGISTER = "passkey_register"
PURPOSE_LOGIN = "passkey_login"
MAX_PASSKEYS_PER_USER = 10

_LOGIN_FAILED = ApiError("Passkey sign-in failed.", status_code=401, code="passkey_login_failed")


def _issue_challenge(settings: Settings, purpose: str, challenge: bytes, user_id: uuid.UUID | None) -> None:
    now = utcnow()
    db.session.execute(delete(AuthChallenge).where(AuthChallenge.expires_at < now - timedelta(hours=1)))
    row = AuthChallenge(
        purpose=purpose,
        challenge=challenge,
        user_id=user_id,
        expires_at=now + timedelta(seconds=settings.auth.challenge_ttl_seconds),
    )
    db.session.add(row)
    db.session.commit()
    session[SESSION_KEY] = str(row.id)


def _consume_challenge(purpose: str, user_id: uuid.UUID | None, error: ApiError) -> bytes:
    """Atomically burn the session's challenge. It is spent even if verification later fails."""
    raw_id = session.pop(SESSION_KEY, None)
    try:
        challenge_id = uuid.UUID(raw_id) if raw_id else None
    except ValueError:
        challenge_id = None
    if challenge_id is None:
        raise error
    row = db.session.get(AuthChallenge, challenge_id)
    if row is None or row.purpose != purpose or row.user_id != user_id:
        raise error
    claimed = db.session.execute(
        update(AuthChallenge)
        .where(
            AuthChallenge.id == challenge_id,
            AuthChallenge.consumed_at.is_(None),
            AuthChallenge.expires_at > utcnow(),
        )
        .values(consumed_at=utcnow())
        .execution_options(synchronize_session=False)
    ).rowcount
    db.session.commit()
    if claimed != 1:
        raise error
    return row.challenge



def begin_registration(settings: Settings, user: User) -> dict:
    if len(user.passkeys) >= MAX_PASSKEYS_PER_USER:
        raise ApiError("Passkey limit reached. Remove one first.", status_code=409, code="passkey_limit")
    options = generate_registration_options(
        rp_id=settings.passkey_rp_id,
        rp_name=settings.app.name,
        user_id=user.webauthn_user_handle,
        user_name=user.email,
        user_display_name=user.display_name,
        exclude_credentials=[PublicKeyCredentialDescriptor(id=p.credential_id) for p in user.passkeys],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    _issue_challenge(settings, PURPOSE_REGISTER, options.challenge, user.id)
    return options_to_json_dict(options)


def finish_registration(settings: Settings, user: User, credential: dict, nickname: str | None) -> PasskeyCredential:
    error = ApiError("Passkey registration failed.", status_code=400, code="passkey_registration_failed")
    challenge = _consume_challenge(PURPOSE_REGISTER, user.id, error)
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=settings.passkey_rp_id,
            expected_origin=settings.passkey_origin,
            require_user_verification=True,
        )
    except Exception as exc:  # library raises many types, incl. KeyError/ValueError on malformed input
        logger.info("Passkey registration rejected: %s", type(exc).__name__)
        record_event("passkey.registration_failed", user.id)
        raise error from None

    transports = None
    if isinstance(credential.get("response"), dict):
        raw = credential["response"].get("transports")
        transports = [t for t in raw if isinstance(t, str)][:8] if isinstance(raw, list) else None
    name = (nickname or "").strip()[:100] or f"Passkey {len(user.passkeys) + 1}"
    row = PasskeyCredential(
        user_id=user.id,
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        transports=transports,
        device_type=verified.credential_device_type.value,
        backed_up=verified.credential_backed_up,
        nickname=name,
    )
    db.session.add(row)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("This passkey is already registered.", status_code=409, code="passkey_exists") from None
    record_event("passkey.registered", user.id, passkey_id=str(row.id))
    return row



def begin_login(settings: Settings) -> dict:
    options = generate_authentication_options(
        rp_id=settings.passkey_rp_id,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    _issue_challenge(settings, PURPOSE_LOGIN, options.challenge, None)
    return options_to_json_dict(options)


def finish_login(settings: Settings, credential: dict) -> User:
    challenge = _consume_challenge(PURPOSE_LOGIN, None, _LOGIN_FAILED)
    try:
        raw_id = base64url_to_bytes(credential["id"])
    except Exception:
        raise _LOGIN_FAILED from None

    stored = db.session.execute(
        select(PasskeyCredential).where(PasskeyCredential.credential_id == raw_id)
    ).scalar_one_or_none()
    user = db.session.get(User, stored.user_id) if stored else None
    if stored is None or user is None or not user.is_active or user.email_verified_at is None:
        record_event("passkey.login_failed", user.id if user else None, reason="unknown_credential")
        raise _LOGIN_FAILED

    # If the authenticator returned a user handle, it must belong to the credential's owner.
    response = credential.get("response") if isinstance(credential.get("response"), dict) else {}
    handle = response.get("userHandle")
    if handle:
        try:
            if base64url_to_bytes(handle) != user.webauthn_user_handle:
                raise ValueError
        except Exception:
            record_event("passkey.login_failed", user.id, reason="user_handle_mismatch")
            raise _LOGIN_FAILED from None

    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=settings.passkey_rp_id,
            expected_origin=settings.passkey_origin,
            credential_public_key=stored.public_key,
            credential_current_sign_count=stored.sign_count,
            require_user_verification=True,
        )
    except Exception as exc:  # includes signature failure and counter regression (cloned authenticator)
        logger.info("Passkey login rejected: %s", type(exc).__name__)
        record_event("passkey.login_failed", user.id, reason=type(exc).__name__)
        raise _LOGIN_FAILED from None

    stored.sign_count = verified.new_sign_count
    stored.last_used_at = utcnow()
    db.session.commit()
    record_event("passkey.login", user.id, passkey_id=str(stored.id))
    return user



def list_passkeys(user: User) -> list[PasskeyCredential]:
    return list(
        db.session.execute(
            select(PasskeyCredential).where(PasskeyCredential.user_id == user.id).order_by(PasskeyCredential.created_at)
        ).scalars()
    )


def remove_passkey(user: User, passkey_id: uuid.UUID) -> None:
    # Ownership is part of the query: another user's id simply doesn't exist for you.
    row = db.session.execute(
        select(PasskeyCredential).where(PasskeyCredential.id == passkey_id, PasskeyCredential.user_id == user.id)
    ).scalar_one_or_none()
    if row is None:
        raise ApiError("Passkey not found.", status_code=404, code="not_found")
    if user.password_hash is None and len(user.passkeys) <= 1:
        raise ApiError(
            "This is your only sign-in method. Set a password before removing it.",
            status_code=409,
            code="last_login_method",
        )
    db.session.delete(row)
    db.session.commit()
    db.session.refresh(user)
    record_event("passkey.removed", user.id, passkey_id=str(passkey_id))
