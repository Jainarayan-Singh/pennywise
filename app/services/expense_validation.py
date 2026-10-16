"""Validation: no draft reaches the review stage with a value the transaction rules would reject.

The pipeline never trusts the model (or its own earlier guesses). Each stage can leave anything in `fields`, so this
runs last: it checks every value against the same rules manual entry uses, against the user's own categories and
accounts, and removes what does not hold up. Whether the removal needs a question is the clarification stage's call.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.models import Account, Category, User
from app.models.finance import PAYMENT_METHODS, TRANSACTION_TYPES
from app.services import expense_fields as f, transaction_service
from app.services.money import MAX_AMOUNT, parse_amount
from app.utils.errors import ValidationFailed


@dataclass(frozen=True)
class Problem:
    field: str
    message: str


def sanitize(user: User, fields: dict, categories: list[Category], accounts: list[Account]) -> list[Problem]:
    """Drop invalid values from `fields` and describe each required one that had to go."""
    problems: list[Problem] = []
    today = transaction_service.user_today(user)

    kind = f.value(fields, "transaction_type")
    if kind is not None and kind not in TRANSACTION_TYPES:
        fields.pop("transaction_type")
        problems.append(Problem("transaction_type", "Was this an expense or income?"))

    if f.value(fields, "amount") is not None:
        try:
            amount = parse_amount(f.value(fields, "amount"))
            if amount > MAX_AMOUNT:
                raise ValidationFailed("amount too large")
        except ValidationFailed:
            fields.pop("amount")
            problems.append(Problem("amount", "That amount can't be used. How much was it?"))

    if (raw_date := f.value(fields, "transaction_date")) is not None:
        try:
            parsed = date.fromisoformat(str(raw_date))
        except ValueError:
            parsed = None
        if parsed is None or parsed > today or parsed < transaction_service.MIN_DATE:
            fields.pop("transaction_date")
            problems.append(Problem("transaction_date", "That date can't be used. On which date was it?"))

    _check_lookup(fields, "category_id", {str(c.id): c for c in categories if not c.is_archived},
                  lambda row: kind is None or row.kind == kind)
    _check_lookup(fields, "account_id", {str(a.id): a for a in accounts if not a.is_archived}, lambda row: True)

    method = f.value(fields, "payment_method")
    if method is not None and method not in PAYMENT_METHODS:
        fields.pop("payment_method")
    for key, limit in (("merchant", 120), ("description", 255)):
        if f.value(fields, key) is not None:
            cleaned = f.clean_text(str(f.value(fields, key)), limit)
            f.put(fields, key, cleaned, f.source(fields, key) or "explicit") if cleaned else fields.pop(key)
    return problems


def _check_lookup(fields: dict, key: str, allowed: dict, fits) -> None:
    """A category or account must be one of the user's own active ones (and a category must match the type)."""
    current = f.value(fields, key)
    if current is not None and (current not in allowed or not fits(allowed[current])):
        fields.pop(key)
