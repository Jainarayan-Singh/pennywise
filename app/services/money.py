"""Deterministic, locale-independent money and currency parsing."""
from __future__ import annotations

import re
from decimal import Decimal

from app.utils.errors import ValidationFailed

CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("999999999999.99")  # NUMERIC(14,2)
_AMOUNT_PATTERN = re.compile(r"\d{1,12}(\.\d{1,2})?")
_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}")


def _invalid(field: str, message: str) -> ValidationFailed:
    return ValidationFailed("Some fields are invalid.", details={field: message})


def parse_amount(value, field: str = "amount") -> Decimal:
    """Accept '250', '250.5', 250, 250.5. Reject commas, exponents, >2 decimals, zero, negatives.

    Nothing is guessed or rounded: ambiguous input is an error, never a silently different number.
    """
    if isinstance(value, bool) or value is None:
        raise _invalid(field, "Enter an amount.")
    if isinstance(value, float):
        text = repr(value)  # shortest round-trip form, avoids binary artefacts like 0.1+0.2
    elif isinstance(value, (int, str)):
        text = str(value).strip()
    else:
        raise _invalid(field, "Enter an amount.")
    if text.startswith("-"):
        raise _invalid(field, "Amount must be greater than zero.")
    if not _AMOUNT_PATTERN.fullmatch(text):
        raise _invalid(field, "Use digits with at most 2 decimal places, e.g. 250 or 250.50.")
    amount = Decimal(text).quantize(CENT)
    if amount <= 0:
        raise _invalid(field, "Amount must be greater than zero.")
    return amount


def normalize_currency(value: str, field: str = "currency") -> str:
    code = value.strip().upper()
    if not _CURRENCY_PATTERN.fullmatch(code):
        raise _invalid(field, "Use a 3-letter currency code such as INR.")
    return code


def format_amount(amount: Decimal) -> str:
    return format(amount.quantize(CENT), "f")
