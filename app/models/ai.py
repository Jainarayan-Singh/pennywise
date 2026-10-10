from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

DRAFT_STATUSES = ("needs_clarification", "ready_for_review", "saved", "cancelled", "expired")
ACTIVE_DRAFT_STATUSES = ("needs_clarification", "ready_for_review")
DRAFT_INPUT_SOURCES = ("text", "voice")


class ExpenseDraft(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    """A pending transaction assembled over one or more messages. Nothing is a transaction until confirmed.

    The original sentence is deliberately not stored: `fields` holds only the resolved values.
    """

    __tablename__ = "expense_drafts"
    __table_args__ = (
        CheckConstraint("status IN ('needs_clarification', 'ready_for_review', 'saved', 'cancelled', 'expired')", name="status_valid"),
        CheckConstraint("input_source IN ('text', 'voice')", name="input_source_valid"),
        Index("ix_expense_drafts_user_id_status", "user_id", "status"),
        Index("ix_expense_drafts_expires_at", "expires_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    input_source: Mapped[str] = mapped_column(String(8), nullable=False, default="text")
    fields: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    pending_field: Mapped[str | None] = mapped_column(String(24))
    question: Mapped[str | None] = mapped_column(String(300))
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    saved_transaction_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("transactions.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
