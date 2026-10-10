from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, Date, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, Uuid, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

CATEGORY_KINDS = ("expense", "income")
ACCOUNT_TYPES = ("cash", "bank", "card", "wallet", "other")
PAYMENT_METHODS = ("cash", "card", "upi", "bank_transfer", "cheque", "other")
TRANSACTION_TYPES = ("expense", "income")
TRANSACTION_SOURCES = ("manual", "voice", "ai", "import", "recurring")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Category(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    """User-owned category. Archived (never deleted) so history and reports stay intact."""

    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint(_in_list("kind", CATEGORY_KINDS), name="kind_valid"),
        Index("uq_categories_user_kind_name", "user_id", "kind", func.lower(db.column("name")), unique=True),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def to_public_dict(self) -> dict:
        return {"id": str(self.id), "name": self.name, "kind": self.kind, "is_archived": self.is_archived}


class Account(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    """Where money lives (cash, bank, card, wallet). Balances are derived, never stored."""

    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(_in_list("account_type", ACCOUNT_TYPES), name="type_valid"),
        Index("uq_accounts_user_name", "user_id", func.lower(db.column("name")), unique=True),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    account_type: Mapped[str] = mapped_column(String(10), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def to_public_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "account_type": self.account_type,
            "currency": self.currency,
            "is_archived": self.is_archived,
        }


class Transaction(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(_in_list("type", TRANSACTION_TYPES), name="type_valid"),
        CheckConstraint(_in_list("source", TRANSACTION_SOURCES), name="source_valid"),
        CheckConstraint(
            "payment_method IS NULL OR " + _in_list("payment_method", PAYMENT_METHODS), name="payment_method_valid"
        ),
        UniqueConstraint("user_id", "idempotency_key", name="uq_transactions_user_idempotency_key"),
        Index("ix_transactions_user_id_transaction_date", "user_id", "transaction_date"),
        Index("ix_transactions_user_id_category_id", "user_id", "category_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("categories.id", ondelete="RESTRICT"))
    account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"))
    payment_method: Mapped[str | None] = mapped_column(String(20))
    merchant: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="manual")
    idempotency_key: Mapped[str | None] = mapped_column(String(64))

    category: Mapped[Category | None] = relationship()
    account: Mapped[Account | None] = relationship()

    def to_public_dict(self) -> dict:
        return {
            "id": str(self.id),
            "type": self.type,
            "amount": format(self.amount.quantize(Decimal("0.01")), "f"),
            "currency": self.currency,
            "transaction_date": self.transaction_date.isoformat(),
            "category": self.category.to_public_dict() if self.category else None,
            "account": self.account.to_public_dict() if self.account else None,
            "payment_method": self.payment_method,
            "merchant": self.merchant,
            "description": self.description,
            "notes": self.notes,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
