"""Typed application settings. This is the only module that reads environment variables."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Mapping
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from app.config.brand_fonts import DEFAULT_BRAND_FONT, SUPPORTED_NAMES, BrandFont, find_brand_font

DEFAULT_APP_NAME = "Advanced Expense Tracker"


class ConfigurationError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _str(env: Mapping[str, str], key: str, default: str = "") -> str:
    value = env.get(key)
    return default if value is None or value.strip() == "" else value.strip()


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = _str(env, key)
    if not raw:
        return default
    if raw.lower() in {"1", "true", "yes", "on"}:
        return True
    if raw.lower() in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{key} must be true or false, got {raw!r}.")


def _int(env: Mapping[str, str], key: str, default: int, minimum: int = 0) -> int:
    raw = _str(env, key)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigurationError(f"{key} must be a whole number, got {raw!r}.") from None
    if value < minimum:
        raise ConfigurationError(f"{key} must be at least {minimum}, got {value}.")
    return value


_RATE_UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


def parse_rate_limit(spec: str) -> tuple[int, int]:
    """'5 per minute' -> (5, 60)."""
    match = re.fullmatch(r"\s*(\d+)\s+per\s+(second|minute|hour|day)\s*", spec.lower())
    if not match or int(match.group(1)) < 1:
        raise ConfigurationError(f"Invalid rate limit {spec!r}; expected e.g. '5 per minute'.")
    return int(match.group(1)), _RATE_UNITS[match.group(2)]


def normalize_database_url(url: str) -> str:
    """Make a plain PostgreSQL URL (e.g. from a hosting dashboard) use the psycopg 3 driver."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@dataclass(frozen=True)
class AppSettings:
    env: str = "development"
    secret_key: str = field(default="", repr=False)
    debug: bool = False
    log_level: str = "INFO"
    public_base_url: str = "http://localhost:5000"
    name: str = DEFAULT_APP_NAME
    copyright_year: int = field(default_factory=lambda: date.today().year)
    brand_font: str = DEFAULT_BRAND_FONT
    hub_url: str = ""
    contact_email: str = ""
    hub_name: str = "Sarvadwar"

    @property
    def brand(self) -> BrandFont:
        """The selected brand font (validated at startup, so the lookup always succeeds)."""
        return find_brand_font(self.brand_font) or find_brand_font(DEFAULT_BRAND_FONT)

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def secure_cookies(self) -> bool:
        return self.public_base_url.startswith("https://")

    @property
    def host(self) -> str:
        return urlparse(self.public_base_url).hostname or ""


@dataclass(frozen=True)
class DatabaseSettings:
    url: str = field(default="", repr=False)
    ssl_mode: str = "prefer"
    schema: str = ""  # PostgreSQL schema for all tables; empty uses the connection's default


@dataclass(frozen=True)
class AISettings:
    api_key: str = field(default="", repr=False)
    text_model: str = ""
    fallback_model: str = ""
    timeout_seconds: int = 45
    requests_per_minute: int = 10
    daily_request_budget: int = 0  # 0 = no app-side daily cap
    api_base_url: str = ""
    max_output_tokens: int = 1024
    max_retries: int = 2
    max_concurrent_requests: int = 2
    draft_ttl_minutes: int = 60

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.text_model)

    @property
    def structured_output_model(self) -> str:
        return self.text_model


@dataclass(frozen=True)
class TranscriptionSettings:
    model: str = ""
    max_duration_seconds: int = 60
    max_file_size_mb: int = 10
    supported_formats: tuple[str, ...] = ("wav", "webm", "ogg", "mp3", "m4a")


@dataclass(frozen=True)
class AuthSettings:
    session_lifetime_minutes: int = 720
    password_hash_method: str = "scrypt"
    login_rate_limit: str = "5 per minute"
    password_reset_ttl_minutes: int = 30
    account_setup_ttl_hours: int = 24
    challenge_ttl_seconds: int = 300


PAYLOAD_PLACEHOLDERS = frozenset({"from_email", "to_email", "to_name", "subject", "html", "text", "app_name"})


@dataclass(frozen=True)
class EmailSettings:
    """Email through any HTTP API, described entirely by settings. With no URL, messages go to a local outbox file."""

    service_url: str = ""
    api_key: str = field(default="", repr=False)
    from_email: str = ""
    auth_header: str = "api-key"
    auth_prefix: str = ""
    payload_template: str = ""  # JSON text; {placeholders} inside string values are filled in per message

    @property
    def enabled(self) -> bool:
        return bool(self.service_url)

@dataclass(frozen=True)
class FinanceSettings:
    default_currency: str = "INR"
    default_timezone: str = "Asia/Kolkata"
    default_date_format: str = "DD/MM/YYYY"
    default_number_format: str = "en-IN"


@dataclass(frozen=True)
class Settings:
    app: AppSettings
    database: DatabaseSettings
    ai: AISettings
    transcription: TranscriptionSettings
    auth: AuthSettings
    finance: FinanceSettings
    email: EmailSettings = field(default_factory=EmailSettings)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        settings = cls(
            app=AppSettings(
                env=_str(env, "APP_ENV", "development").lower(),
                secret_key=_str(env, "SECRET_KEY"),
                debug=_bool(env, "DEBUG", False),
                log_level=_str(env, "LOG_LEVEL", "INFO").upper(),
                public_base_url=(_str(env, "APP_BASE_URL") or _str(env, "PUBLIC_BASE_URL", AppSettings.public_base_url)).rstrip("/"),
                name=_str(env, "APP_NAME", DEFAULT_APP_NAME),
                copyright_year=_int(env, "COPYRIGHT_YEAR", date.today().year, 1900),
                brand_font=_str(env, "APP_BRAND_FONT", DEFAULT_BRAND_FONT),
                hub_url=_str(env, "HUB_URL"),
                contact_email=_str(env, "CONTACT_EMAIL"),
                hub_name=_str(env, "HUB_NAME", "Sarvadwar"),
            ),
            database=DatabaseSettings(
                url=_str(env, "DATABASE_URL"),
                ssl_mode=_str(env, "DATABASE_SSL_MODE", "prefer"),
                schema=_str(env, "DATABASE_SCHEMA"),
            ),
            ai=AISettings(
                api_key=_str(env, "AI_API_KEY"),
                text_model=_str(env, "AI_TEXT_MODEL"),
                fallback_model=_str(env, "AI_FALLBACK_MODEL"),
                timeout_seconds=_int(env, "AI_TIMEOUT_SECONDS", AISettings.timeout_seconds, 1),
                requests_per_minute=_int(env, "AI_REQUESTS_PER_MINUTE", AISettings.requests_per_minute, 1),
                daily_request_budget=_int(env, "AI_DAILY_REQUEST_BUDGET", 0, 0),
            ),
            transcription=TranscriptionSettings(model=_str(env, "TRANSCRIPTION_MODEL")),
            auth=AuthSettings(
                session_lifetime_minutes=_int(env, "AUTH_SESSION_LIFETIME", AuthSettings.session_lifetime_minutes, 1),
                password_hash_method=_str(env, "PASSWORD_HASH_METHOD", AuthSettings.password_hash_method),
                login_rate_limit=_str(env, "LOGIN_RATE_LIMIT", AuthSettings.login_rate_limit),
            ),
            finance=FinanceSettings(
                default_currency=_str(env, "DEFAULT_CURRENCY", FinanceSettings.default_currency).upper(),
                default_timezone=_str(env, "DEFAULT_TIMEZONE", FinanceSettings.default_timezone),
            ),
            email=EmailSettings(
                service_url=_str(env, "EMAIL_SERVICE_URL"),
                api_key=env.get("EMAIL_SERVICE_API_KEY", "").strip(),
                from_email=_str(env, "DEFAULT_FROM_EMAIL"),
                auth_header=_str(env, "EMAIL_SERVICE_AUTH_HEADER", EmailSettings.auth_header),
                auth_prefix=_str(env, "EMAIL_SERVICE_AUTH_PREFIX"),
                payload_template=env.get("EMAIL_SERVICE_PAYLOAD_TEMPLATE", "").strip(),
            ),
        )
        settings.validate()
        return settings

    @property
    def passkey_origin(self) -> str:
        """WebAuthn expects exactly the address the browser shows, so it is derived from PUBLIC_BASE_URL."""
        return self.app.public_base_url

    @property
    def passkey_rp_id(self) -> str:
        return self.app.host

    @property
    def voice_enabled(self) -> bool:
        return bool(self.transcription.model and self.ai.api_key)

    def validate(self) -> None:
        problems: list[str] = []
        app = self.app
        if app.env not in {"development", "testing", "production"}:
            problems.append("APP_ENV must be one of: development, testing, production.")
        if not app.secret_key:
            problems.append(
                'SECRET_KEY is required. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
            )
        elif app.is_production and len(app.secret_key) < 32:
            problems.append("SECRET_KEY must be at least 32 characters in production.")
        if not self.database.url:
            problems.append("DATABASE_URL is required.")
        if self.database.schema and not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", self.database.schema):
            problems.append("DATABASE_SCHEMA must be lowercase letters, digits and underscores, e.g. pennywise.")

        origin = urlparse(app.public_base_url)
        if origin.scheme not in {"http", "https"} or not origin.hostname or origin.path or origin.query:
            problems.append("APP_BASE_URL must be a bare origin such as http://localhost:5000 or https://example.com.")
        elif origin.scheme == "http" and (app.is_production or origin.hostname != "localhost"):
            problems.append("APP_BASE_URL must use https (plain http is allowed only for localhost in development).")
        if app.is_production and app.debug:
            problems.append("DEBUG must be false in production.")

        if self.transcription.model and not self.ai.api_key:
            problems.append("TRANSCRIPTION_MODEL requires AI_API_KEY.")
        try:
            parse_rate_limit(self.auth.login_rate_limit)
        except ConfigurationError as error:
            problems.append(str(error))
        if find_brand_font(app.brand_font) is None:
            problems.append(f"APP_BRAND_FONT {app.brand_font!r} is not supported. Use one of: {', '.join(SUPPORTED_NAMES)}.")
        email = self.email
        problems.extend(_email_problems(email, app))
        if len(self.finance.default_currency) != 3:
            problems.append("DEFAULT_CURRENCY must be a 3-letter ISO 4217 code.")
        try:
            ZoneInfo(self.finance.default_timezone)
        except Exception:
            problems.append(f"DEFAULT_TIMEZONE {self.finance.default_timezone!r} is not a valid IANA zone.")
        if problems:
            raise ConfigurationError("Invalid configuration:\n - " + "\n - ".join(problems))

    @property
    def sqlalchemy_url(self) -> str:
        return normalize_database_url(self.database.url)

    def sqlalchemy_engine_options(self) -> dict:
        """Engine options; engine-specific bits are isolated here."""
        url = self.sqlalchemy_url
        if url.startswith("sqlite"):
            return {}
        options: dict = {"pool_size": 5, "max_overflow": 5, "pool_timeout": 30, "pool_pre_ping": True, "pool_recycle": 1800}
        if url.startswith("postgresql") and self.database.ssl_mode:
            options["connect_args"] = {"sslmode": self.database.ssl_mode, "connect_timeout": 5}
        return options

def _email_problems(email: EmailSettings, app: AppSettings) -> list[str]:
    if not email.enabled:
        return ["EMAIL_SERVICE_URL is required in production so account and password emails can be delivered."] if app.is_production else []
    problems = []
    url = urlparse(email.service_url)
    if url.scheme != "https" and not (url.scheme == "http" and not app.is_production):
        problems.append("EMAIL_SERVICE_URL must be an https URL.")
    if not url.hostname:
        problems.append("EMAIL_SERVICE_URL is not a valid URL.")
    for name, value in (("EMAIL_SERVICE_API_KEY", email.api_key), ("DEFAULT_FROM_EMAIL", email.from_email)):
        if not value:
            problems.append(f"{name} is required when EMAIL_SERVICE_URL is set.")
    if not re.fullmatch(r"[A-Za-z0-9-]+", email.auth_header):
        problems.append("EMAIL_SERVICE_AUTH_HEADER must be a header name such as api-key or Authorization.")
    problems.extend(_payload_problems(email.payload_template))
    return problems


def _payload_problems(template: str) -> list[str]:
    if not template:
        return ["EMAIL_SERVICE_PAYLOAD_TEMPLATE is required when EMAIL_SERVICE_URL is set."]
    try:
        parsed = json.loads(template)
    except ValueError as error:
        return [f"EMAIL_SERVICE_PAYLOAD_TEMPLATE is not valid JSON ({error.msg})."]
    if not isinstance(parsed, dict):
        return ["EMAIL_SERVICE_PAYLOAD_TEMPLATE must be a JSON object."]
    used = set(re.findall(r"\{(\w+)\}", template))
    unknown = used - PAYLOAD_PLACEHOLDERS
    if unknown:
        return [f"EMAIL_SERVICE_PAYLOAD_TEMPLATE uses unknown placeholders: {', '.join(sorted(unknown))}. Use: {', '.join(sorted(PAYLOAD_PLACEHOLDERS))}."]
    return []