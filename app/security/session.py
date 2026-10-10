from __future__ import annotations

import uuid
from datetime import timedelta
from functools import wraps
from urllib.parse import urlparse

from flask import current_app, redirect, request, session, url_for
from sqlalchemy import delete, update
from werkzeug.exceptions import HTTPException

from app.extensions import db
from app.models import AuthSession, User
from app.models.base import as_utc, utcnow
from app.security.csrf import rotate_csrf_token
from app.utils.errors import ApiError

DEFAULT_LANDING_PATH = "/dashboard"
_UNSET = object()
_NOT_A_DESTINATION = ("static", "health.", "auth_api.", "ai_api.", "finance_api.", "main.")
_NOT_A_DESTINATION_PAGES = {"auth_pages.login_page", "auth_pages.reset_password_page"}


def get_current_user() -> User | None:
    """Resolve the signed-in user once per request. Every request re-checks the server-side session record."""
    cached = getattr(request, "_current_user", _UNSET)
    if cached is not _UNSET:
        return cached
    user = _load_user()
    if user is None:
        for key in ("uid", "sid", "sv"):
            session.pop(key, None)
    request._current_user = user
    return user


def _load_user() -> User | None:
    try:
        user_id, session_id = uuid.UUID(session["uid"]), uuid.UUID(session["sid"])
    except (KeyError, ValueError, TypeError):
        return None
    record = db.session.get(AuthSession, session_id)
    if record is None or record.user_id != user_id or record.revoked_at is not None or as_utc(record.expires_at) <= utcnow():
        return None
    user = db.session.get(User, user_id)
    if user is None or not user.is_active or user.email_verified_at is None or session.get("sv") != user.session_version:
        return None
    return user


def start_session(user: User) -> None:
    """Create a fresh authenticated session: a new server-side record and a new cookie (prevents fixation)."""
    lifetime = timedelta(minutes=current_app.extensions["settings"].auth.session_lifetime_minutes)
    now = utcnow()
    db.session.execute(delete(AuthSession).where(AuthSession.expires_at < now - timedelta(days=1)))
    record = AuthSession(user_id=user.id, expires_at=now + lifetime)
    db.session.add(record)
    db.session.commit()

    session.clear()
    session["uid"] = str(user.id)
    session["sid"] = str(record.id)
    session["sv"] = user.session_version
    session.permanent = True
    rotate_csrf_token()
    request._current_user = user


def end_session() -> None:
    """Revoke this browser's server-side session so a copied cookie is worthless, then clear the cookie."""
    try:
        session_id = uuid.UUID(session["sid"])
    except (KeyError, ValueError, TypeError):
        session_id = None
    if session_id is not None:
        db.session.execute(
            update(AuthSession).where(AuthSession.id == session_id, AuthSession.revoked_at.is_(None)).values(revoked_at=utcnow())
        )
        db.session.commit()
    session.clear()
    request._current_user = None


def post_login_path(raw: str | None) -> str:
    """Return `raw` only if it is a same-site path to a real page; otherwise the dashboard.

    Rejects absolute and protocol-relative URLs, backslashes, control characters, and endpoints that
    would loop (login, reset) or are not pages (API, static, public landing).
    """
    if not raw or not raw.startswith("/") or raw.startswith("//") or "\\" in raw or any(ord(c) < 32 for c in raw):
        return DEFAULT_LANDING_PATH
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        return DEFAULT_LANDING_PATH
    try:
        endpoint, _ = current_app.url_map.bind("").match(parsed.path, method="GET")
    except HTTPException:
        return DEFAULT_LANDING_PATH
    if endpoint in _NOT_A_DESTINATION_PAGES or endpoint.startswith(_NOT_A_DESTINATION):
        return DEFAULT_LANDING_PATH
    return parsed.path


def api_login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if get_current_user() is None:
            raise ApiError("Authentication required.", status_code=401, code="unauthenticated")
        return view(*args, **kwargs)

    return wrapper


def page_login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if get_current_user() is None:
            return redirect(url_for("auth_pages.login_page", next=request.path))
        return view(*args, **kwargs)

    return wrapper
