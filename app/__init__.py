from __future__ import annotations

from datetime import timedelta

from flask import Flask
from sqlalchemy import event

from app.config import Settings
from app.extensions import db, migrate
from app.integrations.ai import build_ai_provider
from app.integrations.email import build_email_sender
from app.integrations.transcription import build_transcriber
from app.security.csrf import register_csrf
from app.security.headers import register_security_headers
from app.security.origin import register_canonical_origin
from app.security.rate_limit import RateLimiter
from app.utils.errors import register_error_handlers
from app.utils.logging_setup import configure_logging, register_request_id


def _use_schema(app: Flask, schema: str) -> None:
    """Make every database connection work in `schema` (the name is validated at startup, so it is safe to inline)."""
    with app.app_context():
        engine = db.engine

    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute(f'SET search_path TO "{schema}"')
        cursor.close()
        dbapi_connection.commit()


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or Settings.from_env()
    configure_logging(settings.app.log_level)

    app = Flask(__name__, instance_relative_config=True)
    app.extensions["settings"] = settings
    app.config.update(
        SECRET_KEY=settings.app.secret_key,
        DEBUG=settings.app.debug,
        TESTING=settings.app.env == "testing",
        SESSION_COOKIE_SECURE=settings.app.secure_cookies,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=settings.auth.session_lifetime_minutes),
        SQLALCHEMY_DATABASE_URI=settings.sqlalchemy_url,
        SQLALCHEMY_ENGINE_OPTIONS=settings.sqlalchemy_engine_options(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=settings.transcription.max_file_size_mb * 1024 * 1024,
    )

    db.init_app(app)
    from app import models  # noqa: F401  (registers every model with SQLAlchemy and Alembic)

    migrate.init_app(app, db)
    if settings.database.schema and settings.sqlalchemy_url.startswith("postgresql"):
        _use_schema(app, settings.database.schema)
    app.extensions["rate_limiter"] = RateLimiter()
    app.extensions["email_sender"] = build_email_sender(settings, app.instance_path)
    ai_provider = build_ai_provider(settings)
    app.extensions["ai_provider"] = ai_provider
    # Transcription shares the text provider's usage guard so both count against the same free-tier quota.
    app.extensions["transcriber"] = build_transcriber(settings, getattr(ai_provider, "usage", None))

    register_request_id(app)
    register_error_handlers(app)
    register_canonical_origin(app, settings)
    register_csrf(app)
    register_security_headers(app, settings)

    from app.blueprints.ai_assistant import ai_api_bp, ai_pages_bp
    from app.blueprints.auth import auth_api_bp, auth_pages_bp
    from app.blueprints.finance import finance_api_bp, finance_pages_bp
    from app.blueprints.health import health_bp
    from app.blueprints.main import main_bp

    for blueprint in (
        health_bp, main_bp, auth_api_bp, auth_pages_bp, finance_api_bp, finance_pages_bp, ai_api_bp, ai_pages_bp,
    ):
        app.register_blueprint(blueprint)

    return app
