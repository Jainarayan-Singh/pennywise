"""Categories and accounts: user-owned lookup data. Archive instead of delete."""
from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Account, Category, User
from app.models.base import utcnow
from app.models.finance import ACCOUNT_TYPES, CATEGORY_KINDS
from app.services.money import normalize_currency
from app.utils.errors import ApiError, ValidationFailed

ArchiveScope = Literal["active", "archived", "all"]

# Created per user on first use (not hardcoded in any frontend file).
DEFAULT_CATEGORIES = {
    "expense": (
        "Food & Dining", "Groceries", "Transport", "Fuel", "Shopping", "Bills & Utilities",
        "Rent", "Health", "Education", "Entertainment", "Travel", "Other",
    ),
    "income": ("Salary", "Freelance", "Interest", "Gift", "Other income"),
}


def _clean_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not 1 <= len(name) <= 60:
        raise ValidationFailed("Some fields are invalid.", details={"name": "Enter a name up to 60 characters."})
    return name


def ensure_defaults(user: User) -> None:
    """Seed default categories once. Safe to call repeatedly and concurrently."""
    prefs = user.preferences
    if prefs is None or prefs.defaults_seeded_at is not None:
        return
    existing = {
        (kind, name.lower())
        for kind, name in db.session.execute(
            select(Category.kind, Category.name).where(Category.user_id == user.id)
        )
    }
    for kind, names in DEFAULT_CATEGORIES.items():
        for name in names:
            if (kind, name.lower()) not in existing:
                db.session.add(Category(user_id=user.id, name=name, kind=kind))
    prefs.defaults_seeded_at = utcnow()
    try:
        db.session.commit()
    except IntegrityError:  # another request seeded at the same moment
        db.session.rollback()


def _by_archive_scope(stmt, model, scope: ArchiveScope):
    if scope == "active":
        return stmt.where(model.is_archived.is_(False))
    if scope == "archived":
        return stmt.where(model.is_archived.is_(True))
    return stmt


def list_categories(user: User, *, scope: ArchiveScope = "active") -> list[Category]:
    ensure_defaults(user)
    stmt = select(Category).where(Category.user_id == user.id).order_by(Category.kind, func.lower(Category.name))
    return list(db.session.execute(_by_archive_scope(stmt, Category, scope)).scalars())


def get_category(user: User, category_id: uuid.UUID) -> Category:
    row = db.session.execute(
        select(Category).where(Category.id == category_id, Category.user_id == user.id)
    ).scalar_one_or_none()
    if row is None:
        raise ApiError("Category not found.", status_code=404, code="not_found")
    return row


def create_category(user: User, *, name: str, kind: str) -> Category:
    if kind not in CATEGORY_KINDS:
        raise ValidationFailed("Some fields are invalid.", details={"kind": "Must be expense or income."})
    ensure_defaults(user)
    row = Category(user_id=user.id, name=_clean_name(name), kind=kind)
    db.session.add(row)
    _commit_unique(row, "A category with this name already exists.")
    return row


def update_category(user: User, category_id: uuid.UUID, *, name: str | None, is_archived: bool | None) -> Category:
    row = get_category(user, category_id)
    if name is not None:
        row.name = _clean_name(name)
    if is_archived is not None:
        row.is_archived = is_archived
    _commit_unique(row, "A category with this name already exists.")
    return row


def list_accounts(user: User, *, scope: ArchiveScope = "active") -> list[Account]:
    stmt = select(Account).where(Account.user_id == user.id).order_by(func.lower(Account.name))
    return list(db.session.execute(_by_archive_scope(stmt, Account, scope)).scalars())


def get_account(user: User, account_id: uuid.UUID) -> Account:
    row = db.session.execute(
        select(Account).where(Account.id == account_id, Account.user_id == user.id)
    ).scalar_one_or_none()
    if row is None:
        raise ApiError("Account not found.", status_code=404, code="not_found")
    return row


def create_account(user: User, *, name: str, account_type: str, currency: str | None) -> Account:
    if account_type not in ACCOUNT_TYPES:
        raise ValidationFailed("Some fields are invalid.", details={"account_type": f"Must be one of: {', '.join(ACCOUNT_TYPES)}."})
    code = normalize_currency(currency) if currency else user.preferences.currency
    row = Account(user_id=user.id, name=_clean_name(name), account_type=account_type, currency=code)
    db.session.add(row)
    _commit_unique(row, "An account with this name already exists.")
    return row


def update_account(user: User, account_id: uuid.UUID, *, name: str | None, is_archived: bool | None) -> Account:
    # Type and currency are immutable: changing them would silently reinterpret past transactions.
    row = get_account(user, account_id)
    if name is not None:
        row.name = _clean_name(name)
    if is_archived is not None:
        row.is_archived = is_archived
    _commit_unique(row, "An account with this name already exists.")
    return row


def _commit_unique(row, conflict_message: str) -> None:
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError(conflict_message, status_code=409, code="duplicate_name") from None
