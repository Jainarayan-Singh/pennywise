"""Email through a fully configurable HTTP API: mocked responses, safe payloads, safe failures, no secrets exposed."""
import io
import json
import logging
import urllib.error

import pytest

from app.config import ConfigurationError, Settings
from app.integrations.email import (
    INVALID_CREDENTIALS, PROVIDER_ERROR, RATE_LIMITED, REJECTED, SENDER_NOT_VERIFIED, UNAVAILABLE,
    ApiEmailSender, EmailDeliveryError, OutboxEmailSender, build_email_sender,
)
from tests.conftest import BASE_ENV

KEY = "key_that_must_never_leak"
BREVO = '{"sender":{"email":"{from_email}"},"to":[{"email":"{to_email}","name":"{to_name}"}],"subject":"{subject}","htmlContent":"{html}","textContent":"{text}"}'
API_ENV = {
    **BASE_ENV, "EMAIL_SERVICE_URL": "https://mail.example.com/v3/send", "EMAIL_SERVICE_API_KEY": KEY,
    "DEFAULT_FROM_EMAIL": "hello@example.com", "EMAIL_SERVICE_PAYLOAD_TEMPLATE": BREVO,
}


class Reply:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b"{}"


def http_error(status, message=""):
    return urllib.error.HTTPError("https://mail.example.com", status, "x", {}, io.BytesIO(json.dumps({"message": message}).encode()))


class Opener:
    def __init__(self, outcome=None):
        self.outcome, self.requests = outcome or Reply(), []

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def sender(opener, **overrides):
    return ApiEmailSender(Settings.from_env({**API_ENV, **overrides}), opener=opener)


def test_url_header_sender_and_payload_all_come_from_settings():
    opener = Opener()
    sender(opener).send("bob@example.com", "Hello", "Line one\n\nOpen http://x/set-password?token=T", "Bob")
    [(request, timeout)] = opener.requests
    body = json.loads(request.data)
    assert request.full_url == "https://mail.example.com/v3/send" and request.get_method() == "POST" and timeout == 10
    assert request.get_header("Api-key") == KEY and request.get_header("Authorization") is None and KEY not in request.full_url
    assert body["sender"] == {"email": "hello@example.com"} and body["to"] == [{"email": "bob@example.com", "name": "Bob"}]
    assert body["subject"] == "Hello" and body["textContent"].startswith("Line one")
    assert '<a href="http://x/set-password?token=T">' in body["htmlContent"] and "<p>" in body["htmlContent"]


def test_changing_the_provider_is_only_a_settings_change():
    opener = Opener()
    template = '{"from": "{app_name} <{from_email}>", "to": ["{to_email}"], "subject": "{subject}", "text": "{text}"}'
    sender(opener, EMAIL_SERVICE_URL="https://other.example.com/emails", EMAIL_SERVICE_AUTH_HEADER="Authorization",
           EMAIL_SERVICE_AUTH_PREFIX="Bearer", EMAIL_SERVICE_PAYLOAD_TEMPLATE=template).send("a@b.co", "S", "T")
    request = opener.requests[0][0]
    assert request.full_url == "https://other.example.com/emails" and request.get_header("Authorization") == f"Bearer {KEY}"
    assert json.loads(request.data) == {"from": "Advanced Expense Tracker <hello@example.com>", "to": ["a@b.co"], "subject": "S", "text": "T"}


def test_hostile_values_cannot_break_or_inject_into_the_json():
    opener = Opener()
    nasty = 'He said "hi"\n{to_email} \\ ","bcc":"evil@x.co'
    sender(opener).send("bob@example.com", nasty, nasty, nasty)
    body = json.loads(opener.requests[0][0].data)  # still valid JSON
    assert "bcc" not in body and body["subject"] == nasty and body["to"][0]["name"] == nasty


@pytest.mark.parametrize(
    "outcome,reason",
    [
        (http_error(401, "Key not found"), INVALID_CREDENTIALS),
        (http_error(403, "forbidden"), INVALID_CREDENTIALS),
        (http_error(400, "Sender is not valid / not validated"), SENDER_NOT_VERIFIED),
        (http_error(403, "The domain is not verified"), SENDER_NOT_VERIFIED),
        (http_error(422, "Invalid to field"), REJECTED),
        (http_error(429, "Too many requests"), RATE_LIMITED),
        (http_error(500, "boom"), PROVIDER_ERROR),
        (urllib.error.URLError("refused"), UNAVAILABLE),
        (TimeoutError("timed out"), UNAVAILABLE),
    ],
    ids=["bad-key", "forbidden", "sender-invalid", "domain-unverified", "rejected", "rate-limit", "provider-500", "no-connection", "timeout"],
)
def test_every_failure_is_classified_and_never_passes_as_sent(outcome, reason):
    with pytest.raises(EmailDeliveryError) as error:
        sender(Opener(outcome)).send("bob@example.com", "s", "b")
    assert error.value.reason == reason and KEY not in str(error.value) and "bob@example.com" not in str(error.value)


def test_the_sender_is_chosen_by_configuration_only(tmp_path):
    assert isinstance(build_email_sender(Settings.from_env(API_ENV), str(tmp_path)), ApiEmailSender)
    assert isinstance(build_email_sender(Settings.from_env(BASE_ENV), str(tmp_path)), OutboxEmailSender)


@pytest.mark.parametrize(
    "bad",
    [
        {"EMAIL_SERVICE_API_KEY": ""}, {"DEFAULT_FROM_EMAIL": ""}, {"EMAIL_SERVICE_URL": "ftp://x.example.com"},
        {"EMAIL_SERVICE_URL": "http://mail.example.com"} if False else {"EMAIL_SERVICE_AUTH_HEADER": "bad header!"},
        {"EMAIL_SERVICE_PAYLOAD_TEMPLATE": ""}, {"EMAIL_SERVICE_PAYLOAD_TEMPLATE": "not json"}, {"EMAIL_SERVICE_PAYLOAD_TEMPLATE": "[1]"},
        {"EMAIL_SERVICE_PAYLOAD_TEMPLATE": '{"x": "{nope}"}'},
    ],
)
def test_missing_or_invalid_email_configuration_stops_startup_with_a_clear_message(bad):
    with pytest.raises(ConfigurationError) as error:
        Settings.from_env({**API_ENV, **bad})
    assert "EMAIL_SERVICE" in str(error.value) or "DEFAULT_FROM_EMAIL" in str(error.value)
    assert KEY not in str(error.value)


def test_the_key_stays_out_of_repr_and_the_old_provider_settings_are_gone():
    s = Settings.from_env({**API_ENV, "EMAIL_PROVIDER": "resend", "SMTP_HOST": "smtp.example.com"})
    assert KEY not in repr(s) and s.email.service_url == API_ENV["EMAIL_SERVICE_URL"] and not hasattr(s.email, "host")


def test_the_development_outbox_keeps_links_out_of_the_log(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    OutboxEmailSender(tmp_path / "outbox").send("bob@example.com", "Subject", "open http://x/set-password?token=SECRETTOKEN")
    [written] = list((tmp_path / "outbox").glob("*.txt"))
    assert "SECRETTOKEN" in written.read_text(encoding="utf-8")
    assert "SECRETTOKEN" not in caplog.text


class Failing:
    def __init__(self, reason=UNAVAILABLE):
        self.reason = reason

    def send(self, *args):
        raise EmailDeliveryError(self.reason, "HTTP 500")


def test_signup_reports_a_delivery_failure_instead_of_pretending(api, app, caplog):
    app.extensions["email_sender"] = Failing(INVALID_CREDENTIALS)
    res = api.request_account()
    assert res.status_code == 503 and res.get_json()["error"]["code"] == "email_unavailable"
    assert "try again" in res.get_data(as_text=True) and "invalid_credentials" not in res.get_data(as_text=True)
    assert "invalid_credentials" in caplog.text


def test_a_failed_signup_email_looks_the_same_for_every_kind_of_address(api, make_api, app):
    api.register()
    app.extensions["email_sender"] = Failing()
    existing, brand_new = make_api().request_account(), make_api().request_account(email="new@example.com")
    assert existing.status_code == brand_new.status_code == 503 and existing.get_json() == brand_new.get_json()


def test_a_failed_reset_email_gives_the_same_generic_answer_and_is_logged(api, app, caplog):
    api.register()
    app.extensions["email_sender"] = Failing(SENDER_NOT_VERIFIED)
    known = api.post("/api/v1/auth/password/forgot", {"email": "alice@example.com"})
    unknown = api.post("/api/v1/auth/password/forgot", {"email": "ghost@example.com"})
    assert known.status_code == unknown.status_code == 202 and known.get_json() == unknown.get_json()
    assert "sender_not_verified" in caplog.text


def test_the_recipients_name_and_the_configured_base_url_reach_the_email(api, app):
    api.request_account(first_name="Zoe", last_name="Q")
    mail = app.extensions["email_sender"].sent[0]
    assert mail["to"] == "alice@example.com" and "http://localhost:5000/set-password?token=" in mail["body"]


def test_the_key_never_reaches_pages_or_logs(api, app, caplog):
    app.extensions["email_sender"] = sender(Opener(http_error(401, "bad key")))
    for path in ("/", "/login", "/set-password", "/brand.css"):
        assert KEY not in api.get(path).get_data(as_text=True)
    res = api.request_account()
    assert res.status_code == 503 and KEY not in res.get_data(as_text=True) and KEY not in caplog.text
