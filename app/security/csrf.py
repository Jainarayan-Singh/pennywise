"""Session-bound CSRF protection for every state-changing request.

The token lives in the signed session cookie and must be echoed back in the
X-CSRF-Token header (JS reads it from the page's <meta name="csrf-token">).
"""
from __future__ import annotations

import hmac
import secrets

from flask import Flask, request, session

from app.utils.errors import ApiError

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
HEADER = "X-CSRF-Token"


def get_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def rotate_csrf_token() -> str:
    session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def register_csrf(app: Flask) -> None:
    @app.before_request
    def _enforce_csrf() -> None:
        if request.method in SAFE_METHODS:
            return
        expected = session.get("csrf_token")
        supplied = request.headers.get(HEADER, "")
        if not expected or not hmac.compare_digest(expected, supplied):
            raise ApiError("Missing or invalid CSRF token. Reload the page and try again.", status_code=403, code="csrf_failed")

    app.jinja_env.globals["csrf_token"] = get_csrf_token
