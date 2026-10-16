"""The shape of a draft's fields, shared by every stage of the expense pipeline.

Each field is stored as {"value", "source", "note"?}. `source` says how the value became known:

  explicit  the user said it (or chose it in the review form)
  rule      worked out by a fixed rule from something the user said (a date phrase)
  inferred  a suggestion from the user's own data or wording; shown for confirmation
  default   a documented default (the currency of the account, or of the user's preferences)

Keys that start with an underscore are bookkeeping for the pipeline, never transaction fields.
"""
from __future__ import annotations

REQUIRED_ORDER = ("amount", "transaction_type", "transaction_date")
FIELD_LABELS = (
    ("transaction_type", "Type"), ("amount", "Amount"), ("transaction_date", "Date"),
    ("category_id", "Category"), ("account_id", "Account"), ("payment_method", "Payment method"),
    ("merchant", "Merchant"), ("description", "Description"),
)
EDITABLE_FIELDS = {key for key, _ in FIELD_LABELS}
# Optional fields that are worth one question when they could not be resolved (asked at most once each, skippable).
ASKED_ONCE = ("account_id", "category_id")

_ASKED = "_asked"
_CANDIDATES = "_candidates"
_UNMATCHED = "_unmatched"


def put(fields: dict, key: str, value, source: str, note: str | None = None) -> None:
    fields[key] = {"value": value, "source": source, **({"note": note} if note else {})}


def value(fields: dict, key: str):
    entry = fields.get(key)
    return entry["value"] if entry else None


def source(fields: dict, key: str) -> str | None:
    entry = fields.get(key)
    return entry["source"] if entry else None


def is_explicit(fields: dict, key: str) -> bool:
    return source(fields, key) == "explicit"


def clean_text(raw: str | None, limit: int) -> str | None:
    text = " ".join((raw or "").split())
    return text[:limit] or None


# --- bookkeeping: how often each field was asked about, and which accounts are still plausible ---


def times_asked(fields: dict, key: str) -> int:
    return int((value(fields, _ASKED) or {}).get(key, 0))


def mark_asked(fields: dict, key: str) -> None:
    counts = dict(value(fields, _ASKED) or {})
    counts[key] = counts.get(key, 0) + 1
    put(fields, _ASKED, counts, "system")


def set_account_candidates(fields: dict, ids: list[str]) -> None:
    if ids:
        put(fields, _CANDIDATES, {"account_id": ids}, "system")
    else:
        fields.pop(_CANDIDATES, None)


def account_candidates(fields: dict) -> list[str]:
    return list((value(fields, _CANDIDATES) or {}).get("account_id", []))


def set_unmatched_account(fields: dict, phrase: str | None) -> None:
    """Remember an account name the user gave that is not one of theirs, so it is asked about rather than guessed."""
    if phrase:
        put(fields, _UNMATCHED, {"account_id": phrase[:40]}, "system")
    else:
        fields.pop(_UNMATCHED, None)


def unmatched_account(fields: dict) -> str | None:
    return (value(fields, _UNMATCHED) or {}).get("account_id")
