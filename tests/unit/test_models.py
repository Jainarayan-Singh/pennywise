"""Database constraints and deletion behaviour (meaningful on SQLite and PostgreSQL)."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import AuditEvent, AuthChallenge, PasskeyCredential, User, UserPreference
from app.models.base import utcnow


def make_user(email="a@example.com"):
    user = User(email=email, display_name="A", password_hash="x")
    user.preferences = UserPreference(currency="INR", timezone="Asia/Kolkata", date_format="DD/MM/YYYY")
    return user


def test_email_must_be_unique(app):
    db.session.add(make_user())
    db.session.commit()
    db.session.add(make_user())
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_email_must_be_lowercase_at_database_level(app):
    db.session.add(make_user("Mixed@Example.com"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_defaults_and_timestamps_are_timezone_aware_utc(app):
    user = make_user()
    db.session.add(user)
    db.session.commit()
    db.session.refresh(user)
    assert user.is_active is True and user.session_version == 1
    assert len(user.webauthn_user_handle) == 32
    if db.engine.dialect.name == "postgresql":
        # timestamptz is stored as UTC but returned in the session time zone; the instant must match.
        assert user.created_at.tzinfo is not None
        assert abs((user.created_at - utcnow()).total_seconds()) < 60


def test_deleting_user_cascades_to_owned_rows_and_keeps_audit_trail(app):
    user = make_user()
    user.passkeys.append(
        PasskeyCredential(credential_id=b"c1", public_key=b"k", sign_count=0, device_type="single_device", nickname="n")
    )
    db.session.add(user)
    db.session.commit()
    db.session.add_all(
        [
            AuthChallenge(purpose="passkey_login", challenge=b"x", user_id=user.id, expires_at=utcnow()),
            AuditEvent(user_id=user.id, event_type="auth.login"),
        ]
    )
    db.session.commit()

    db.session.delete(user)
    db.session.commit()
    assert db.session.query(PasskeyCredential).count() == 0
    assert db.session.query(UserPreference).count() == 0
    # Cascades are enforced by PostgreSQL; SQLite needs PRAGMA foreign_keys, so assert only there.
    if db.engine.dialect.name == "postgresql":
        assert db.session.query(AuthChallenge).count() == 0
        audit = db.session.query(AuditEvent).one()
        assert audit.user_id is None  # event kept, link severed


def test_credential_id_must_be_unique(app):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    for user in (a, b):
        user.passkeys.append(
            PasskeyCredential(credential_id=b"same", public_key=b"k", sign_count=0, device_type="x", nickname="n")
        )
    db.session.add_all([a, b])
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
