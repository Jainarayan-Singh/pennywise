from __future__ import annotations

import uuid

from flask import Blueprint, current_app, jsonify, request
from pydantic import BaseModel, ConfigDict, Field

from app.security.csrf import get_csrf_token
from app.security.rate_limit import enforce_rate_limit
from app.security.session import api_login_required, end_session, get_current_user, start_session
from app.services import authentication_service as auth_service
from app.services import passkey_service
from app.services.audit_service import record_event
from app.utils.errors import ApiError
from app.utils.validation import parse_json_body

auth_api_bp = Blueprint("auth_api", __name__, url_prefix="/api/v1/auth")

GENERIC_LOGIN_ERROR = "Incorrect email or password."


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=2048)


class RegisterBody(_Body):
    first_name: str = Field(max_length=100)
    last_name: str = Field(max_length=100)
    email: str


class LoginBody(_Body):
    email: str
    password: str


class ForgotBody(_Body):
    email: str


class DeleteAccountBody(_Body):
    email: str


class ResetBody(_Body):
    token: str
    new_password: str
    confirm_password: str


def _settings():
    return current_app.extensions["settings"]


def _ok(data=None, status: int = 200):
    return jsonify({"ok": True, "data": data}), status


def _session_payload(user) -> dict:
    return {
        "authenticated": user is not None,
        "user": user.to_public_dict() if user else None,
        "csrf_token": get_csrf_token(),
    }


@auth_api_bp.get("/session")
def session_state():
    """Current auth state plus a CSRF token for scripts."""
    return _ok(_session_payload(get_current_user()))


@auth_api_bp.post("/register")
def register():
    enforce_rate_limit("register")
    body = parse_json_body(RegisterBody)
    auth_service.register_account(_settings(), first_name=body.first_name, last_name=body.last_name, email=body.email)
    # Same answer for new, pending and existing addresses; the link in the email is the only way forward.
    return _ok({"message": "Check your email for a link to finish creating your account."}, 202)


@auth_api_bp.post("/login")
def login():
    body = parse_json_body(LoginBody)
    enforce_rate_limit("login", f"email:{body.email.strip().lower()[:320]}")
    user = auth_service.authenticate(body.email, body.password)
    if user is None:
        raise ApiError(GENERIC_LOGIN_ERROR, status_code=401, code="invalid_credentials")
    start_session(user)
    record_event("auth.login", user.id, method="password")
    return _ok(_session_payload(user))


@auth_api_bp.post("/logout")
def logout():
    user = get_current_user()
    if user:
        record_event("auth.logout", user.id)
    end_session()
    return _ok(_session_payload(None))


@auth_api_bp.post("/logout-all")
@api_login_required
def logout_all():
    auth_service.revoke_all_sessions(get_current_user())
    end_session()
    return _ok(_session_payload(None))


@auth_api_bp.post("/password/forgot")
def forgot_password():
    enforce_rate_limit("password_forgot")
    body = parse_json_body(ForgotBody)
    auth_service.request_password_reset(_settings(), body.email)
    # Identical response whether or not the account exists.
    return _ok({"message": "If an account exists for that email, a reset link has been sent."}, 202)


@auth_api_bp.post("/password/reset")
def reset_password():
    enforce_rate_limit("password_reset")
    body = parse_json_body(ResetBody)
    auth_service.set_password(_settings(), body.token, body.new_password, body.confirm_password)
    end_session()
    return _ok({"message": "Your password is set. You can now sign in."})



@auth_api_bp.get("/passkeys")
@api_login_required
def list_passkeys():
    return _ok({"passkeys": [p.to_public_dict() for p in passkey_service.list_passkeys(get_current_user())]})


@auth_api_bp.post("/passkeys/register/options")
@api_login_required
def passkey_register_options():
    return _ok(passkey_service.begin_registration(_settings(), get_current_user()))


@auth_api_bp.post("/passkeys/register/verify")
@api_login_required
def passkey_register_verify():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("credential"), dict):
        raise ApiError("Request body must include a credential.", status_code=400, code="invalid_json")
    nickname = payload.get("nickname")
    row = passkey_service.finish_registration(
        _settings(), get_current_user(), payload["credential"], nickname if isinstance(nickname, str) else None
    )
    return _ok({"passkey": row.to_public_dict()}, 201)


@auth_api_bp.post("/passkeys/login/options")
def passkey_login_options():
    enforce_rate_limit("passkey_login")
    return _ok(passkey_service.begin_login(_settings()))


@auth_api_bp.post("/passkeys/login/verify")
def passkey_login_verify():
    enforce_rate_limit("passkey_login")
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("credential"), dict):
        raise ApiError("Request body must include a credential.", status_code=400, code="invalid_json")
    user = passkey_service.finish_login(_settings(), payload["credential"])
    start_session(user)
    return _ok(_session_payload(user))


@auth_api_bp.delete("/passkeys/<passkey_id>")
@api_login_required
def delete_passkey(passkey_id: str):
    try:
        parsed = uuid.UUID(passkey_id)
    except ValueError:
        raise ApiError("Passkey not found.", status_code=404, code="not_found") from None
    passkey_service.remove_passkey(get_current_user(), parsed)
    return _ok({"removed": True})


@auth_api_bp.delete("/account")
@api_login_required
def delete_account():
    user = get_current_user()
    enforce_rate_limit("delete-account", f"user:{user.id}")
    body = parse_json_body(DeleteAccountBody)
    auth_service.delete_account(user, body.email)
    end_session()
    return _ok(_session_payload(None))
