import pytest

from app.config import ConfigurationError, Settings
from app.config.settings import normalize_database_url
from tests.conftest import BASE_ENV


def env(**overrides):
    return {**BASE_ENV, **overrides}


def test_missing_secret_key_fails_clearly():
    with pytest.raises(ConfigurationError, match="SECRET_KEY"):
        Settings.from_env(env(SECRET_KEY=""))


def test_missing_database_url_fails_clearly():
    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        Settings.from_env(env(DATABASE_URL=""))


def test_optional_integrations_may_be_disabled():
    s = Settings.from_env(env())
    assert not s.ai.enabled
    assert s.voice_enabled is False


PROD = {
    "APP_ENV": "production", "APP_BASE_URL": "https://app.example.com", "EMAIL_SERVICE_URL": "https://mail.example.com/send",
    "EMAIL_SERVICE_API_KEY": "k", "DEFAULT_FROM_EMAIL": "hi@app.example.com", "EMAIL_SERVICE_PAYLOAD_TEMPLATE": '{"to": "{to_email}"}',
}


def test_production_rules_enforced():
    with pytest.raises(ConfigurationError) as exc:
        Settings.from_env(env(APP_ENV="production", DEBUG="true"))
    msg = str(exc.value)
    assert "DEBUG must be false" in msg
    assert "APP_BASE_URL must use https" in msg


def test_production_accepts_an_explicit_https_origin():
    s = Settings.from_env(env(**PROD))
    assert s.app.secure_cookies and s.passkey_origin == "https://app.example.com" and s.passkey_rp_id == "app.example.com"


def test_email_defaults_to_a_local_outbox_and_is_required_in_production():
    assert not Settings.from_env(env()).email.enabled
    with pytest.raises(ConfigurationError, match="EMAIL_SERVICE_URL"):
        Settings.from_env(env(**{**PROD, "EMAIL_SERVICE_URL": ""}))


def test_passkey_origin_and_rp_id_come_from_the_app_base_url():
    s = Settings.from_env(env(APP_BASE_URL="http://localhost:5000"))
    assert s.passkey_origin == "http://localhost:5000" and s.passkey_rp_id == "localhost"
    assert not s.app.secure_cookies


def test_the_old_public_base_url_name_still_works_and_the_new_one_wins():
    assert Settings.from_env(env(PUBLIC_BASE_URL="http://localhost:6000")).app.public_base_url == "http://localhost:6000"
    both = env(APP_BASE_URL="http://localhost:5000", PUBLIC_BASE_URL="http://localhost:6000")
    assert Settings.from_env(both).app.public_base_url == "http://localhost:5000"


@pytest.mark.parametrize("url", ["http://app.example.com", "http://localhost:5000/login", "localhost:5000", "ftp://localhost"])
def test_the_base_url_must_be_a_safe_bare_origin(url):
    with pytest.raises(ConfigurationError, match="APP_BASE_URL"):
        Settings.from_env(env(APP_BASE_URL=url))

def test_invalid_int_and_bool_rejected():
    with pytest.raises(ConfigurationError, match="AI_TIMEOUT_SECONDS"):
        Settings.from_env(env(AI_TIMEOUT_SECONDS="abc"))
    with pytest.raises(ConfigurationError, match="DEBUG"):
        Settings.from_env(env(DEBUG="maybe"))


def test_invalid_timezone_rejected():
    with pytest.raises(ConfigurationError, match="DEFAULT_TIMEZONE"):
        Settings.from_env(env(DEFAULT_TIMEZONE="Mars/Olympus"))


def test_database_url_normalized_for_psycopg3():
    assert normalize_database_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url("sqlite:///x.db") == "sqlite:///x.db"


def test_secrets_not_in_repr():
    s = Settings.from_env(env())
    assert "test-only-secret" not in repr(s)
