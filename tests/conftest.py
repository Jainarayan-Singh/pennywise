import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app import create_app
from app.config import Settings
from app.config.settings import normalize_database_url
from app.extensions import db
from tests.helpers import ApiClient

BASE_ENV = {
    "APP_ENV": "testing",
    "SECRET_KEY": "test-only-secret-key-not-for-real-use-0123456789",
    # Default: isolated in-memory SQLite. Set TEST_DATABASE_URL to run the same suite on PostgreSQL.
    "DATABASE_URL": "sqlite+pysqlite:///:memory:",
    "DATABASE_SSL_MODE": "prefer",
    "LOGIN_RATE_LIMIT": "1000 per minute",
    "PASSWORD_HASH_METHOD": "pbkdf2:sha256:1000",  # fast hashing for tests only
}


class FakeEmailSender:
    def __init__(self):
        self.sent = []

    def send(self, to_address, subject, body, to_name=""):
        self.sent.append({"to": to_address, "subject": subject, "body": body})


class FakeAIProvider:
    """Scripted stand-in for the AI provider. Any call that wasn't queued fails the test."""

    def __init__(self):
        self.queue = []
        self.prompts = []

    def push(self, result):
        self.queue.append(result)

    def generate_structured(self, *, system, user, schema):
        self.prompts.append(user)
        if not self.queue:
            raise AssertionError("unexpected AI call")
        result = self.queue.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def generate_text(self, *, system, user):
        raise AssertionError("unexpected AI call")

    def check_health(self):
        return True

    @property
    def calls(self):
        return len(self.prompts)


class FakeTranscriber:
    def __init__(self):
        self.result = "Yesterday I paid 1200 for petrol"
        self.received = []

    def transcribe_audio(self, audio, mime_type):
        self.received.append((audio, mime_type))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture(scope="session")
def database_url():
    """SQLite by default. With TEST_DATABASE_URL, a throwaway schema is created and dropped.

    search_path is pinned to that schema only, so tests can never see or touch
    tables in `public` (i.e. the real application data).
    """
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        yield BASE_ENV["DATABASE_URL"]
        return
    base = normalize_database_url(url)
    schema = f"aet_test_{uuid.uuid4().hex[:10]}"
    engine = create_engine(base)
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = make_url(base).update_query_dict({"options": f"-csearch_path={schema}"})
    try:
        yield scoped.render_as_string(hide_password=False)
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


@pytest.fixture()
def settings(database_url):
    return Settings.from_env({**BASE_ENV, "DATABASE_URL": database_url})


@pytest.fixture()
def app(settings):
    application = create_app(settings)
    application.extensions["email_sender"] = FakeEmailSender()
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def api(client):
    return ApiClient(client)


@pytest.fixture()
def make_api(app):
    """Factory for independent browsers (separate cookie jars)."""
    return lambda: ApiClient(app.test_client())


@pytest.fixture()
def ai(app):
    provider = FakeAIProvider()
    app.extensions["ai_provider"] = provider
    return provider


@pytest.fixture()
def voice(app):
    transcriber = FakeTranscriber()
    app.extensions["transcriber"] = transcriber
    return transcriber
