"""Safe database connectivity check. Never returns credentials or raw driver errors."""
from __future__ import annotations

import logging
import time

from flask import current_app
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db

logger = logging.getLogger(__name__)

PASSWORD_PLACEHOLDER = "YOUR_LOCAL_POSTGRES_PASSWORD"

# SQLSTATE -> (reason code, user-facing message)
_SQLSTATE_REASONS = {
    "28P01": ("authentication_failed", "The database rejected the username or password."),
    "28000": ("authentication_failed", "The database rejected the username or password."),
    "3D000": ("database_not_found", "The configured database does not exist on the server."),
}


def _result(connected: bool, reason: str, message: str, **extra) -> dict:
    return {"connected": connected, "reason": reason, "message": message, **extra}


def check_database() -> dict:
    settings = current_app.extensions["settings"]
    if PASSWORD_PLACEHOLDER in settings.database.url:
        return _result(
            False,
            "password_not_configured",
            "DATABASE_URL still contains the password placeholder. Edit .env and restart the app.",
        )

    started = time.perf_counter()
    try:
        db.session.execute(text("SELECT 1"))
        version = None
        if db.engine.dialect.name == "postgresql":
            version = db.session.execute(text("SHOW server_version")).scalar()
        latency_ms = round((time.perf_counter() - started) * 1000)
        db.session.rollback()  # read-only check; release the connection cleanly
        return _result(
            True,
            "ok",
            "Connected to the database.",
            engine=db.engine.dialect.name,
            server_version=version,
            latency_ms=latency_ms,
        )
    except SQLAlchemyError as exc:
        db.session.rollback()
        sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
        reason, message = _SQLSTATE_REASONS.get(
            sqlstate,
            ("unreachable", "Could not reach the database server. Check that PostgreSQL is running and the host/port are correct."),
        )
        # Log only the exception type and SQLSTATE; never the URL or driver message.
        logger.warning("Database check failed: %s (sqlstate=%s)", type(exc).__name__, sqlstate)
        return _result(False, reason, message)
