import re

from app import create_app
from app.config import Settings
from app.extensions import db
from app.models import AuditEvent, PasswordResetToken, User
from app.models.base import utcnow
from tests.conftest import BASE_ENV, FakeEmailSender

PASSWORD = "correct horse battery"


def test_signup_creates_a_pending_account_that_cannot_sign_in(api, make_api, app):
    res = api.request_account(email="  Alice@Example.COM ")
    assert res.status_code == 202 and "Check your email" in res.get_json()["data"]["message"]
    user = db.session.query(User).one()
    assert user.email == "alice@example.com" and user.display_name == "Alice Tester"
    assert user.password_hash is None and user.email_verified_at is None
    assert user.preferences.currency == "INR"
    assert api.get("/api/v1/auth/session").get_json()["data"]["authenticated"] is False  # no session yet
    assert make_api().login(password="anything at all 123").status_code == 401
    [mail] = app.extensions["email_sender"].sent
    assert mail["to"] == "alice@example.com" and "http://localhost:5000/set-password?token=" in mail["body"]


def test_the_emailed_link_sets_the_password_and_activates_the_account(api, make_api):
    api.request_account()
    token = api.emailed_token()
    assert db.session.query(PasswordResetToken).one().token_hash != token  # only a hash is stored
    assert api.set_password(token).status_code == 200
    user = db.session.query(User).one()
    assert user.email_verified_at is not None and user.password_hash and PASSWORD not in user.password_hash
    assert make_api().login().status_code == 200
    assert api.set_password(token, "another passphrase 99").status_code == 400  # a link works once


def test_signup_answers_the_same_for_new_pending_and_existing_addresses(api, make_api, app):
    first = api.request_account()
    again = api.request_account()  # still pending: a fresh link goes out
    sender = app.extensions["email_sender"]
    old_token, new_token = api.emailed_token(0), api.emailed_token(1)
    assert api.set_password(old_token).status_code == 400  # the earlier link was replaced
    assert api.set_password(new_token).status_code == 200
    sender.sent.clear()
    existing = make_api().request_account()  # a finished account: only a notice, never a link
    assert first.get_json() == again.get_json() == existing.get_json() and existing.status_code == 202
    [notice] = sender.sent
    assert "token=" not in notice["body"] and "already have" in notice["subject"]
    assert db.session.query(User).count() == 1


def test_signup_validates_names_and_email_without_creating_anything(api):
    for body in (
        {"first_name": "", "last_name": "Tester", "email": "a@b.co"},
        {"first_name": "Al1ce", "last_name": "Tester", "email": "a@b.co"},
        {"first_name": "Alice", "last_name": "<script>", "email": "a@b.co"},
        {"first_name": "Alice", "last_name": "Tester", "email": "nope"},
    ):
        assert api.post("/api/v1/auth/register", body).status_code == 422, body
    assert db.session.query(User).count() == 0
    ok = api.request_account(first_name="Anne-Marie", last_name="O'Neil")
    assert ok.status_code == 202 and db.session.query(User).one().display_name == "Anne-Marie O'Neil"


def test_signup_rejects_a_password_and_unknown_fields(api):
    body = {"first_name": "A", "last_name": "B", "email": "a@b.co"}
    assert api.post("/api/v1/auth/register", {**body, "password": PASSWORD}).status_code == 422
    assert api.post("/api/v1/auth/register", {**body, "is_admin": True}).status_code == 422
    res = api.client.post("/api/v1/auth/register", data="x", headers={"X-CSRF-Token": api.refresh_csrf()})
    assert res.status_code == 400


def test_an_account_without_a_finished_setup_can_never_authenticate(api, make_api):
    api.register()
    user = db.session.query(User).one()
    user.email_verified_at = None  # e.g. a half-finished account that somehow has a password
    db.session.commit()
    assert make_api().login().status_code == 401
    assert api.get("/api/v1/auth/session").get_json()["data"]["authenticated"] is False  # existing cookies stop too


def test_setup_needs_matching_passwords_and_a_mismatch_keeps_the_link(api):
    api.request_account()
    token = api.emailed_token()
    mismatch = api.set_password(token, PASSWORD, confirm="a different passphrase")
    assert mismatch.status_code == 422 and "confirm_password" in mismatch.get_json()["error"]["details"]
    assert api.set_password(token, "short", confirm="short").status_code == 422
    assert api.set_password(token).status_code == 200  # neither failure burned the token


def test_setup_links_expire(api, app):
    api.request_account()
    token = api.emailed_token()
    record = db.session.query(PasswordResetToken).one()
    record.expires_at = utcnow().replace(year=2000)
    db.session.commit()
    assert api.set_password(token).status_code == 400
    assert db.session.query(User).one().email_verified_at is None


def test_emailed_links_use_the_configured_origin_not_the_request_host(api, app):
    spoofed = "http://evil.example"
    csrf = api.client.get("/api/v1/auth/session", base_url=spoofed).get_json()["data"]["csrf_token"]
    res = api.client.post(
        "/api/v1/auth/register",
        json={"first_name": "A", "last_name": "B", "email": "a@b.co"},
        headers={"X-CSRF-Token": csrf},
        base_url=spoofed,
    )
    assert res.status_code == 202
    assert "evil.example" not in app.extensions["email_sender"].sent[0]["body"]
    assert "http://localhost:5000/set-password?token=" in app.extensions["email_sender"].sent[0]["body"]

def test_csrf_required_for_state_changing_requests(api):
    res = api.post("/api/v1/auth/login", {"email": "a@b.co", "password": "x"}, csrf=False)
    assert res.status_code == 403 and res.get_json()["error"]["code"] == "csrf_failed"
    api.csrf = "wrong-token"
    assert api.post("/api/v1/auth/logout").status_code == 403


def test_login_success_and_generic_failures(api, make_api):
    api.register()
    other = make_api()
    ok = other.login()
    assert ok.status_code == 200

    wrong_pw = make_api().login(password="wrong password here")
    unknown = make_api().login(email="nobody@example.com")
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.get_json() == unknown.get_json()  # no account enumeration
    assert wrong_pw.get_json()["error"]["message"] == "Incorrect email or password."


def test_login_rotates_csrf_and_session_identity(api, make_api):
    api.register()
    browser = make_api()
    before = browser.refresh_csrf()
    browser.login()
    assert browser.csrf != before  # fresh token after privilege change (fixation defence)
    assert browser.client.get("/api/v1/auth/session").get_json()["data"]["authenticated"]


def test_logout_ends_session(api):
    api.register()
    assert api.post("/api/v1/auth/logout").status_code == 200
    assert api.get("/api/v1/auth/session").get_json()["data"]["authenticated"] is False
    assert api.get("/api/v1/auth/passkeys").status_code == 401


def test_logout_everywhere_revokes_other_sessions(api, make_api):
    api.register()
    laptop, phone = make_api(), make_api()
    laptop.login()
    phone.login()
    assert api.post("/api/v1/auth/logout-all").status_code == 200
    for browser in (laptop, phone, api):
        assert browser.client.get("/api/v1/auth/session").get_json()["data"]["authenticated"] is False


def test_deactivated_user_loses_access(api, make_api):
    api.register()
    user = db.session.query(User).one()
    user.is_active = False
    db.session.commit()
    assert api.get("/api/v1/auth/session").get_json()["data"]["authenticated"] is False
    assert make_api().login().status_code == 401


def test_login_rate_limit_blocks_brute_force():
    env = {**BASE_ENV, "LOGIN_RATE_LIMIT": "3 per minute"}
    app = create_app(Settings.from_env(env))
    with app.app_context():
        db.create_all()
        from tests.helpers import ApiClient

        browser = ApiClient(app.test_client())
        codes = [browser.login(password=f"guess number {i}").status_code for i in range(5)]
        assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]
        assert browser.login().status_code == 429  # even the right password is throttled
        db.drop_all()


def test_failed_logins_are_audited_without_secrets(api, make_api):
    api.register()
    make_api().login(password="wrong password here")
    events = db.session.query(AuditEvent).filter_by(event_type="auth.login_failed").all()
    assert len(events) == 1 and "wrong password" not in str(events[0].details)


# --- password recovery ------------------------------------------------------------------


def _request_reset(api, app, email="alice@example.com"):
    res = api.post("/api/v1/auth/password/forgot", {"email": email})
    sender: FakeEmailSender = app.extensions["email_sender"]
    return res, sender


def test_forgot_password_is_generic_for_known_and_unknown_accounts(api, app):
    api.register()
    known, sender = _request_reset(api, app)
    unknown, _ = _request_reset(api, app, "ghost@example.com")
    assert known.status_code == unknown.status_code == 202
    assert known.get_json() == unknown.get_json()
    assert len(sender.sent) == 1 and sender.sent[0]["to"] == "alice@example.com"


def test_reset_token_flow_single_use_and_revokes_sessions(api, make_api, app):
    api.register()
    other = make_api()
    other.login()
    _, sender = _request_reset(api, app)
    token = re.search(r"token=([\w-]+)", sender.sent[0]["body"]).group(1)
    assert "/reset-password?token=" in sender.sent[0]["body"]
    assert db.session.query(PasswordResetToken).filter(PasswordResetToken.used_at.is_(None)).one().token_hash != token  # stored hashed

    anon = make_api()
    new_password = "a brand new passphrase"
    assert anon.set_password(token, new_password).status_code == 200
    assert anon.set_password(token, "another passphrase!").status_code == 400  # single use, no replay
    # old sessions revoked, old password dead, new password works
    assert other.client.get("/api/v1/auth/session").get_json()["data"]["authenticated"] is False
    assert make_api().login(password=PASSWORD).status_code == 401
    assert make_api().login(password=new_password).status_code == 200


def test_reset_rejects_expired_bogus_and_superseded_tokens(api, make_api, app):
    api.register()
    _, sender = _request_reset(api, app)
    first = re.search(r"token=([\w-]+)", sender.sent[0]["body"]).group(1)
    _, sender = _request_reset(api, app)  # newer link supersedes the first
    second = re.search(r"token=([\w-]+)", sender.sent[1]["body"]).group(1)
    anon = make_api()
    assert anon.set_password(first, "a brand new passphrase").status_code == 400
    assert anon.set_password("bogus", "a brand new passphrase").status_code == 400

    record = db.session.query(PasswordResetToken).filter(PasswordResetToken.used_at.is_(None)).one()
    record.expires_at = utcnow().replace(year=2000)
    db.session.commit()
    assert anon.set_password(second, "a brand new passphrase").status_code == 400


def test_reset_enforces_password_policy(api, make_api, app):
    api.register()
    _, sender = _request_reset(api, app)
    token = re.search(r"token=([\w-]+)", sender.sent[0]["body"]).group(1)
    assert make_api().set_password(token, "short").status_code == 422
    # a rejected password must not burn the token
    assert make_api().set_password(token, "a brand new passphrase").status_code == 200


def test_finishing_a_reset_cancels_every_other_outstanding_link(api, make_api, app):
    api.register()
    _request_reset(api, app)
    sender = app.extensions["email_sender"]
    token = re.search(r"token=([\w-]+)", sender.sent[0]["body"]).group(1)
    db.session.add(PasswordResetToken(user_id=db.session.query(User).one().id, token_hash="f" * 64, expires_at=utcnow().replace(year=2100)))
    db.session.commit()
    assert make_api().set_password(token, "a brand new passphrase").status_code == 200
    assert db.session.query(PasswordResetToken).filter(PasswordResetToken.used_at.is_(None)).count() == 0


def test_forgot_password_for_a_pending_account_resends_the_setup_link(api, app):
    api.request_account()
    sender = app.extensions["email_sender"]
    _request_reset(api, app)
    assert len(sender.sent) == 2 and "/set-password?token=" in sender.sent[1]["body"]

# --- pages ------------------------------------------------------------------------------


def test_pages_and_guards(client, api):
    assert client.get("/login").status_code == 200
    res = client.get("/account")
    assert res.status_code == 302 and "/login" in res.headers["Location"]
    api.register()
    assert api.get("/account").status_code == 200
    assert api.get("/login").status_code == 302  # already signed in


def test_auth_pages_have_no_inline_script_or_handlers(client, api):
    api.register()
    for path in ("/login", "/reset-password", "/account"):
        html = api.get(path).get_data(as_text=True) if path == "/account" else client.get(path).get_data(as_text=True)
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), path
        assert not re.search(r"\son\w+=", html), path
        assert "<style" not in html, path
