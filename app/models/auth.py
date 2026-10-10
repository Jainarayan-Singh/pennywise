from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import CreatedAtMixin, UUIDPrimaryKeyMixin
from app.models.user import User


class PasskeyCredential(UUIDPrimaryKeyMixin, CreatedAtMixin, db.Model):
    """A WebAuthn public-key credential. Holds no biometric data of any kind."""

    __tablename__ = "passkey_credentials"
    __table_args__ = (Index("ix_passkey_credentials_user_id", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transports: Mapped[list | None] = mapped_column(JSON)
    device_type: Mapped[str] = mapped_column(String(32), nullable=False)
    backed_up: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    nickname: Mapped[str] = mapped_column(String(100), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="passkeys")

    def to_public_dict(self) -> dict:
        return {
            "id": str(self.id),
            "nickname": self.nickname,
            "device_type": self.device_type,
            "backed_up": self.backed_up,
            "created_at": self.created_at.isoformat(),
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
        }


class AuthSession(UUIDPrimaryKeyMixin, CreatedAtMixin, db.Model):
    """One signed-in browser. The cookie carries only the id; revoking the row ends the session everywhere it is used."""

    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_user_id", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthChallenge(UUIDPrimaryKeyMixin, CreatedAtMixin, db.Model):
    """Single-use, expiring WebAuthn challenge."""

    __tablename__ = "auth_challenges"
    __table_args__ = (Index("ix_auth_challenges_expires_at", "expires_at"),)

    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    challenge: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PasswordResetToken(UUIDPrimaryKeyMixin, CreatedAtMixin, db.Model):
    """Only a SHA-256 hash of the emailed token is stored."""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (Index("ix_password_reset_tokens_user_id", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, db.Model):
    """Security-relevant event log. Never store secrets or financial payloads here."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_user_id_created_at", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    details: Mapped[dict | None] = mapped_column(JSON)
