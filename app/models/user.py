from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, LargeBinary, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.auth import PasskeyCredential


class User(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("email = lower(email)", name="email_lowercase"),)

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Nullable: a passkey-only account has no password.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Bumping this invalidates every existing session cookie for the user.
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Opaque random handle given to authenticators; never the email or the database id.
    webauthn_user_handle: Mapped[bytes] = mapped_column(
        LargeBinary(64), nullable=False, unique=True, default=lambda: os.urandom(32)
    )

    preferences: Mapped["UserPreference"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    passkeys: Mapped[list["PasskeyCredential"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def to_public_dict(self) -> dict:
        return {
            "id": str(self.id),
            "email": self.email,
            "display_name": self.display_name,
            "has_password": self.password_hash is not None,
            "email_verified": self.email_verified_at is not None,
        }


class UserPreference(TimestampMixin, db.Model):
    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    date_format: Mapped[str] = mapped_column(String(20), nullable=False)
    # Set once the default categories have been created for this user (idempotent seeding).
    defaults_seeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="preferences")
