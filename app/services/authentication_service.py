"""Account creation by emailed link, password authentication and password recovery."""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import timedelta

from flask import current_app
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from app.config import Settings
from app.extensions import db
from app.models import PasswordResetToken, User, UserPreference
from app.integrations.email import EmailDeliveryError, deliver
from app.models.base import as_utc, utcnow
from app.services.audit_service import record_event
from app.utils.errors import ApiError, ValidationFailed

logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMAIL_UNAVAILABLE = "We couldn't send the email right now. Please try again in a few minutes."
MAX_NAME_LENGTH = 50
_NAME_PATTERN = re.compile(r"[^\W\d_](?:[^\W\d_]|[ '.\-])*")
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128
COMMON_PASSWORDS = frozenset(
    {"password", "password1", "password123", "1234567890", "qwertyuiop", "iloveyou12", "letmein123", "admin12345", "welcome123"}
)


def normalize_email(raw: str) -> str:
    email = raw.strip().lower()
    if len(email) > 320 or not EMAIL_PATTERN.match(email):
        raise ValidationFailed("Some fields are invalid.", details={"email": "Enter a valid email address."})
    return email


def validate_password(password: str, email: str | None = None) -> None:
    problems = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        problems.append(f"Use at most {MAX_PASSWORD_LENGTH} characters.")
    if password.lower() in COMMON_PASSWORDS:
        problems.append("This password is too common.")
    if email and len(email.split("@")[0]) >= 4 and email.split("@")[0] in password.lower():
        problems.append("Do not include your email name in the password.")
    if len(set(password)) < 4:
        problems.append("Use a more varied password.")
    if problems:
        raise ValidationFailed("Password does not meet the policy.", details={"password": " ".join(problems)})


def hash_password(settings: Settings, password: str) -> str:
    return generate_password_hash(password, method=settings.auth.password_hash_method)


# Verified against when the account does not exist, so response time doesn't reveal it.
_DUMMY_HASH = generate_password_hash("not-a-real-password-for-timing")


def normalize_name(raw: str, field: str, label: str) -> str:
    name = " ".join(raw.split())
    if not _NAME_PATTERN.fullmatch(name) or len(name) > MAX_NAME_LENGTH:
        raise ValidationFailed("Some fields are invalid.", details={field: f"Enter your {label} using letters only."})
    return name


def _new_user(settings: Settings, email: str, display_name: str) -> User:
    user = User(email=email, display_name=display_name, password_hash=None, email_verified_at=None)
    user.preferences = UserPreference(
        currency=settings.finance.default_currency,
        timezone=settings.finance.default_timezone,
        date_format=settings.finance.default_date_format,
    )
    return user


def register_account(settings: Settings, *, first_name: str, last_name: str, email: str) -> None:
    """Start sign-up. The caller always answers the same way, so this never reveals whether an email is taken.

    A new address gets a pending account (no password, unverified) and a setup link. An address that is still
    pending gets a fresh link. A finished account gets a notice that points to sign-in. Nobody can sign in
    until the emailed link has been used to choose a password.
    """
    email = normalize_email(email)
    first = normalize_name(first_name, "first_name", "first name")
    last = normalize_name(last_name, "last_name", "last name")

    user = db.session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        user = _new_user(settings, email, f"{first} {last}")
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:  # a concurrent sign-up for the same address won the race
            db.session.rollback()
            user = db.session.execute(select(User).where(User.email == email)).scalar_one()
        else:
            record_event("user.registered", user.id)

    # Every branch sends exactly one email, so a delivery failure looks the same whatever the address was.
    try:
        if user.email_verified_at is None and user.is_active:
            _send_setup_email(settings, user)
        elif user.is_active:
            _send_existing_account_notice(settings, user)
    except EmailDeliveryError:
        raise ApiError(EMAIL_UNAVAILABLE, status_code=503, code="email_unavailable") from None


def _mail(user: User, subject: str, body: str) -> None:
    deliver(current_app, user.email, subject, body, user.display_name)


def _send_existing_account_notice(settings: Settings, user: User) -> None:
    _mail(user,
        f"You already have a {settings.app.name} account",
        f"Hi {user.display_name.split()[0]},\n\nSomeone tried to create a {settings.app.name} account with this "
        f"email address, but you already have one.\n\nSign in: {settings.app.public_base_url}/login\n"
        "If you forgot your password, use \"Forgot your password?\" on that page.\n\n"
        "If this wasn't you, you can ignore this email.",
    )

def authenticate(email: str, password: str) -> User | None:
    """Return the user on success, None on any failure (callers show one generic message)."""
    try:
        normalized = normalize_email(email)
    except ValidationFailed:
        check_password_hash(_DUMMY_HASH, password)
        return None
    user = db.session.execute(select(User).where(User.email == normalized)).scalar_one_or_none()
    hash_to_check = user.password_hash if user and user.password_hash else _DUMMY_HASH
    password_ok = check_password_hash(hash_to_check, password)
    if user and user.is_active and user.email_verified_at is not None and user.password_hash and password_ok:
        return user
    record_event("auth.login_failed", user.id if user else None)
    return None


def revoke_all_sessions(user: User) -> None:
    user.session_version += 1
    db.session.commit()
    record_event("auth.sessions_revoked", user.id)



def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _issue_token(user: User, ttl: timedelta) -> str:
    """Create a single-use token and return it. Only its hash is stored; earlier unused tokens stop working."""
    now = utcnow()
    _invalidate_tokens(user, now)
    token = secrets.token_urlsafe(32)
    db.session.add(PasswordResetToken(user_id=user.id, token_hash=_hash_token(token), expires_at=now + ttl))
    db.session.commit()
    return token


def _invalidate_tokens(user: User, now) -> None:
    db.session.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )


def _send_setup_email(settings: Settings, user: User) -> None:
    hours = settings.auth.account_setup_ttl_hours
    token = _issue_token(user, timedelta(hours=hours))
    link = f"{settings.app.public_base_url}/set-password?token={token}"
    _mail(user,
        f"Finish setting up your {settings.app.name} account",
        f"Hi {user.display_name.split()[0]},\n\nWelcome to {settings.app.name}. Choose a password to finish creating "
        f"your account. The link works once and expires in {hours} hours:\n\n{link}\n\n"
        "If you didn't sign up, ignore this email: the account can't be used without this step.",
    )


def request_password_reset(settings: Settings, email: str) -> None:
    """Always returns normally; whether the account exists is never revealed."""
    try:
        normalized = normalize_email(email)
    except ValidationFailed:
        return
    user = db.session.execute(select(User).where(User.email == normalized, User.is_active.is_(True))).scalar_one_or_none()
    if user is None:
        return
    try:
        if user.email_verified_at is None:  # never finished sign-up: send the setup link again
            _send_setup_email(settings, user)
            return
        minutes = settings.auth.password_reset_ttl_minutes
        token = _issue_token(user, timedelta(minutes=minutes))
        link = f"{settings.app.public_base_url}/reset-password?token={token}"
        _mail(user,
            f"Reset your {settings.app.name} password",
            f"Use this link to choose a new password. It works once and expires in {minutes} minutes:\n\n{link}\n\n"
            "If you did not request this, ignore this email and your password stays the same.",
        )
        record_event("auth.password_reset_requested", user.id)
    except EmailDeliveryError:
        # Already logged by deliver(). The visitor still gets the generic answer: telling them about a failure
        # would reveal that the address has an account.
        return


def set_password(settings: Settings, token: str, new_password: str, confirm_password: str) -> User:
    """Finish sign-up or reset a password with an emailed token. Opening the link proves the email is theirs."""
    invalid = ApiError("This link is invalid or has expired. Request a new one from the sign-in page.", status_code=400, code="invalid_reset_token")
    record = db.session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == _hash_token(token))
    ).scalar_one_or_none()
    if record is None or record.used_at is not None or as_utc(record.expires_at) <= utcnow():
        raise invalid
    user = db.session.get(User, record.user_id)
    if user is None or not user.is_active:
        raise invalid
    validate_password(new_password, user.email)
    if new_password != confirm_password:
        raise ValidationFailed("Some fields are invalid.", details={"confirm_password": "The passwords don't match."})

    # Single-use: claim the token atomically; a concurrent second use updates 0 rows.
    now = utcnow()
    claimed = db.session.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.id == record.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    ).rowcount
    if claimed != 1:
        db.session.rollback()
        raise invalid
    first_time = user.email_verified_at is None
    user.password_hash = hash_password(settings, new_password)
    user.email_verified_at = user.email_verified_at or now
    user.session_version += 1  # signs out every existing session
    _invalidate_tokens(user, now)  # no other outstanding link can be used after this
    db.session.commit()
    record_event("auth.account_activated" if first_time else "auth.password_reset_completed", user.id)
    return user