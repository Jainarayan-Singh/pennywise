"""Passkey flows verified end-to-end against a software authenticator (real signatures)."""
import pytest

from app.extensions import db
from app.models import AuthChallenge, PasskeyCredential, User
from app.models.base import utcnow
from tests.helpers import SoftAuthenticator

REG = "/api/v1/auth/passkeys/register"
LOGIN = "/api/v1/auth/passkeys/login"


def register_passkey(api, authenticator=None, **overrides):
    authenticator = authenticator or SoftAuthenticator()
    options = api.post(f"{REG}/options").get_json()["data"]
    credential = authenticator.register(options, **overrides)
    res = api.post(f"{REG}/verify", {"credential": credential, "nickname": "Test laptop"})
    return authenticator, options, credential, res


def passkey_login(browser, authenticator, **overrides):
    options = browser.post(f"{LOGIN}/options").get_json()["data"]
    credential = authenticator.authenticate(options, **overrides)
    return browser.post(f"{LOGIN}/verify", {"credential": credential}), options, credential


@pytest.fixture()
def alice(api):
    api.register()
    return api


# --- registration -----------------------------------------------------------------------


def test_registration_requires_signed_in_user(api):
    assert api.post(f"{REG}/options").status_code == 401
    assert api.post(f"{REG}/verify", {"credential": {}}).status_code == 401


def test_registration_options_require_user_verification_and_expose_no_secrets(alice):
    data = alice.post(f"{REG}/options").get_json()["data"]
    assert data["rp"]["id"] == "localhost"
    assert data["authenticatorSelection"]["userVerification"] == "required"
    assert data["user"]["name"] == "alice@example.com"
    user = db.session.query(User).one()
    assert data["user"]["id"] != str(user.id)  # opaque handle, not the DB id


def test_full_registration_stores_public_credential_only(alice):
    _, _, _, res = register_passkey(alice)
    assert res.status_code == 201
    row = db.session.query(PasskeyCredential).one()
    assert row.nickname == "Test laptop" and row.sign_count == 0 and row.transports == ["internal"]
    listed = alice.get("/api/v1/auth/passkeys").get_json()["data"]["passkeys"]
    assert len(listed) == 1 and "public_key" not in listed[0] and "credential_id" not in listed[0]


@pytest.mark.parametrize(
    "overrides",
    [
        {"origin": "https://evil.example"},          # wrong origin
        {"rp_id": "evil.example"},                   # wrong RP ID hash
        {"flags": 0x41},                             # user not verified (no UV)
    ],
)
def test_registration_failure_paths_store_nothing(alice, overrides):
    _, _, _, res = register_passkey(alice, **overrides)
    assert res.status_code == 400 and res.get_json()["error"]["code"] == "passkey_registration_failed"
    assert db.session.query(PasskeyCredential).count() == 0


def test_registration_challenge_is_single_use(alice):
    auth, options, credential, res = register_passkey(alice)
    assert res.status_code == 201
    replay = alice.post(f"{REG}/verify", {"credential": credential})
    assert replay.status_code == 400
    assert db.session.query(PasskeyCredential).count() == 1


def test_failed_attempt_burns_the_challenge(alice):
    auth = SoftAuthenticator()
    options = alice.post(f"{REG}/options").get_json()["data"]
    bad = auth.register(options, origin="https://evil.example")
    assert alice.post(f"{REG}/verify", {"credential": bad}).status_code == 400
    good = auth.register(options)  # correct response, but for an already-spent challenge
    assert alice.post(f"{REG}/verify", {"credential": good}).status_code == 400


def test_expired_challenge_rejected(alice):
    auth = SoftAuthenticator()
    options = alice.post(f"{REG}/options").get_json()["data"]
    row = db.session.query(AuthChallenge).one()
    row.expires_at = utcnow().replace(year=2000)
    db.session.commit()
    res = alice.post(f"{REG}/verify", {"credential": auth.register(options)})
    assert res.status_code == 400 and db.session.query(PasskeyCredential).count() == 0


def test_verify_without_options_or_with_garbage_is_rejected(alice):
    assert alice.post(f"{REG}/verify", {"credential": {"id": "x"}}).status_code == 400
    alice.post(f"{REG}/options")
    assert alice.post(f"{REG}/verify", {"credential": {"id": "x", "response": 5}}).status_code == 400
    assert alice.post(f"{REG}/verify", {"nope": 1}).status_code == 400


def test_challenge_bound_to_user_cannot_be_used_by_another_account(alice, make_api):
    options = alice.post(f"{REG}/options").get_json()["data"]
    challenge_id = db.session.query(AuthChallenge).one().id
    mallory = make_api()
    mallory.register(email="mallory@example.com", name="Mallory")
    with mallory.client.session_transaction() as sess:
        sess["passkey_challenge_id"] = str(challenge_id)  # stolen id
    res = mallory.post(f"{REG}/verify", {"credential": SoftAuthenticator().register(options)})
    assert res.status_code == 400 and db.session.query(PasskeyCredential).count() == 0


def test_duplicate_credential_not_registered_twice(alice, make_api):
    auth, *_ = register_passkey(alice)
    bob = make_api()
    bob.register(email="bob@example.com", name="Bob")
    options = bob.post(f"{REG}/options").get_json()["data"]
    res = bob.post(f"{REG}/verify", {"credential": auth.register(options)})  # same credential id
    assert res.status_code == 409 and db.session.query(PasskeyCredential).count() == 1


# --- authentication ---------------------------------------------------------------------


def test_passkey_login_success_creates_session_and_updates_counter(alice, make_api):
    auth, *_ = register_passkey(alice)
    browser = make_api()
    res, *_ = passkey_login(browser, auth)
    assert res.status_code == 200 and res.get_json()["data"]["user"]["email"] == "alice@example.com"
    assert browser.get("/api/v1/auth/session").get_json()["data"]["authenticated"] is True
    row = db.session.query(PasskeyCredential).one()
    assert row.sign_count == 1 and row.last_used_at is not None


def test_login_options_are_public_and_require_user_verification(client, api):
    data = api.post(f"{LOGIN}/options").get_json()["data"]
    assert data["userVerification"] == "required" and data["rpId"] == "localhost"
    assert data.get("allowCredentials") in (None, [])


def test_replayed_assertion_is_rejected(alice, make_api):
    auth, *_ = register_passkey(alice)
    browser = make_api()
    res, options, credential = passkey_login(browser, auth)
    assert res.status_code == 200
    other = make_api()
    other.post(f"{LOGIN}/options")
    assert other.post(f"{LOGIN}/verify", {"credential": credential}).status_code == 401  # different challenge
    assert browser.post(f"{LOGIN}/verify", {"credential": credential}).status_code == 401  # spent challenge


def test_counter_regression_detects_cloned_authenticator(alice, make_api):
    auth, *_ = register_passkey(alice)
    assert passkey_login(make_api(), auth, counter=5)[0].status_code == 200
    res, *_ = passkey_login(make_api(), auth, counter=5)  # not strictly increasing
    assert res.status_code == 401
    assert passkey_login(make_api(), auth, counter=3)[0].status_code == 401
    assert db.session.query(PasskeyCredential).one().sign_count == 5


@pytest.mark.parametrize(
    "overrides",
    [
        {"tamper_signature": True},
        {"origin": "https://evil.example"},
        {"rp_id": "evil.example"},
        {"flags": 0x01},                       # user present but not verified
        {"user_handle": b"someone-elses-handle-0123456789ab"},
    ],
)
def test_login_failure_paths_are_generic_and_create_no_session(alice, make_api, overrides):
    auth, *_ = register_passkey(alice)
    browser = make_api()
    res, *_ = passkey_login(browser, auth, **overrides)
    assert res.status_code == 401 and res.get_json()["error"]["code"] == "passkey_login_failed"
    assert browser.get("/api/v1/auth/session").get_json()["data"]["authenticated"] is False


def test_unknown_credential_rejected(alice, make_api):
    register_passkey(alice)
    stranger = SoftAuthenticator()
    res, *_ = passkey_login(make_api(), stranger)
    assert res.status_code == 401


def test_register_challenge_cannot_be_used_for_login(alice, make_api):
    auth, *_ = register_passkey(alice)
    # Issue a *registration* challenge, then try to finish a login with it.
    options = alice.post(f"{REG}/options").get_json()["data"]
    res = alice.post(f"{LOGIN}/verify", {"credential": auth.authenticate(options)})
    assert res.status_code == 401


def test_deactivated_user_cannot_use_passkey(alice, make_api):
    auth, *_ = register_passkey(alice)
    db.session.query(User).one().is_active = False
    db.session.commit()
    assert passkey_login(make_api(), auth)[0].status_code == 401


# --- management / isolation -------------------------------------------------------------


def test_user_cannot_delete_another_users_passkey(alice, make_api):
    register_passkey(alice)
    passkey_id = db.session.query(PasskeyCredential).one().id
    mallory = make_api()
    mallory.register(email="mallory@example.com", name="Mallory")
    assert mallory.delete(f"/api/v1/auth/passkeys/{passkey_id}").status_code == 404
    assert mallory.get("/api/v1/auth/passkeys").get_json()["data"]["passkeys"] == []
    assert db.session.query(PasskeyCredential).count() == 1
    assert alice.delete("/api/v1/auth/passkeys/not-a-uuid").status_code == 404


def test_owner_can_remove_passkey_and_it_stops_working(alice, make_api):
    auth, *_ = register_passkey(alice)
    passkey_id = db.session.query(PasskeyCredential).one().id
    assert alice.delete(f"/api/v1/auth/passkeys/{passkey_id}").status_code == 200
    assert db.session.query(PasskeyCredential).count() == 0
    assert passkey_login(make_api(), auth)[0].status_code == 401


def test_cannot_remove_last_login_method_of_passkey_only_account(alice):
    register_passkey(alice)
    user = db.session.query(User).one()
    user.password_hash = None
    db.session.commit()
    passkey_id = db.session.query(PasskeyCredential).one().id
    res = alice.delete(f"/api/v1/auth/passkeys/{passkey_id}")
    assert res.status_code == 409 and res.get_json()["error"]["code"] == "last_login_method"


def test_second_passkey_excludes_existing_credentials(alice):
    first, *_ = register_passkey(alice)
    options = alice.post(f"{REG}/options").get_json()["data"]
    assert len(options["excludeCredentials"]) == 1
    # same authenticator trying again is refused by the browser; server also refuses duplicates
    res = alice.post(f"{REG}/verify", {"credential": first.register(options)})
    assert res.status_code == 409
