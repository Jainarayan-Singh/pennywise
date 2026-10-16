"""Clarification: decide whether a draft is ready, and if not, ask the single most useful next question.

Fields fall into four states for the review and for this stage:
  known      said by the user, or fixed by a rule from what they said
  inferred   a suggestion from their wording or history, shown for confirmation
  missing    required (amount, type, date) and not available
  ambiguous  several accounts fit, or nothing fits and the user has to choose

Required fields are always asked about. Category and account are optional in the data model, so each is asked
about at most once, only when it could not be resolved, with the user's own options to tap and a way to skip.
Nothing is asked twice in the same words: a repeated question says what it still needs.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select

from app.extensions import db
from app.models import Account, Category, Transaction, User
from app.services import expense_fields as f
from app.services.expense_validation import Problem

MAX_OPTIONS = 8
SKIP_WORDS = {"skip", "none", "no", "nope", "nothing", "no account", "uncategorised", "uncategorized", "leave it", "n/a"}
_CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}

# A combined question is only used for these pairs, so the one answer ("500 yesterday") can settle both.
_COMBINED = ("amount", "transaction_date")


@dataclass(frozen=True)
class Step:
    status: str  # needs_clarification | ready_for_review
    pending_field: str | None = None
    question: str | None = None


def next_step(user: User, fields: dict, problems: list[Problem], categories: list[Category], accounts: list[Account],
              *, extra_problem: tuple[str, str] | None = None) -> Step:
    """Inspect the validated fields and choose what happens next. Records that an optional field was asked about."""
    reasons = {p.field: p.message for p in problems}

    if extra_problem:  # even when an older value exists, a correction that could not be applied is asked about
        f.mark_asked(fields, extra_problem[1])
        return Step("needs_clarification", extra_problem[1], extra_problem[0])

    missing = [key for key in f.REQUIRED_ORDER if not f.value(fields, key)]
    if missing:
        pending = _combine(missing, reasons)
        first = pending.split(",")[0]
        question = reasons.get(first) if len(pending.split(",")) == 1 and reasons.get(first) else _question(fields, pending)
        f.mark_asked(fields, first)
        return Step("needs_clarification", pending, question)

    active_accounts = [a for a in accounts if not a.is_archived]
    if (key := _next_optional(fields, categories, active_accounts)) is not None:
        f.mark_asked(fields, key)
        return Step("needs_clarification", key, _optional_question(fields, key))
    return Step("ready_for_review")


def _combine(missing: list[str], reasons: dict) -> str:
    if missing == list(_COMBINED) and not any(reasons.get(key) for key in _COMBINED):
        return ",".join(_COMBINED)
    return missing[0]


def _question(fields: dict, pending: str) -> str:
    repeated = f.times_asked(fields, pending.split(",")[0]) > 0
    if pending == ",".join(_COMBINED):
        return "I still need the amount and the date. For example “500 yesterday”." if repeated else "How much was it, and on which date?"
    if pending == "amount":
        return "I still need an amount, like 250 or 2.5k." if repeated else "How much was it?"
    if pending == "transaction_type":
        return "Please answer “expense” or “income”." if repeated else "Was this an expense or income?"
    verb = {"expense": "spend", "income": "receive"}.get(f.value(fields, "transaction_type"))
    if repeated:
        return "I still need a date, like “yesterday” or “12 October”."
    return f"On which date did you {verb} {_money_label(fields)}?" if verb and f.value(fields, "amount") else "On which date was this?"


def _money_label(fields: dict) -> str:
    amount, currency = Decimal(f.value(fields, "amount")), f.value(fields, "currency") or ""
    text = f"{amount:f}".rstrip("0").rstrip(".") if amount == amount.to_integral() else f"{amount:.2f}"
    symbol = _CURRENCY_SYMBOLS.get(currency)
    return f"{symbol}{text}" if symbol else f"{currency} {text}".strip()


# --- optional fields: asked once, from the user's own options ---------------------------------


def _next_optional(fields: dict, categories: list[Category], accounts: list[Account]) -> str | None:
    kind = f.value(fields, "transaction_type")
    for key in f.ASKED_ONCE:
        if f.value(fields, key) or f.times_asked(fields, key):
            continue
        if key == "account_id" and (len(accounts) >= 2 or (accounts and f.unmatched_account(fields))):
            return key
        if key == "category_id" and any(not c.is_archived and c.kind == kind for c in categories):
            return key
    return None


def _optional_question(fields: dict, key: str) -> str:
    kind = f.value(fields, "transaction_type")
    if key == "account_id" and (phrase := f.unmatched_account(fields)):
        return f"I couldn't find an account called “{phrase}”. Which account was it?"
    if key == "account_id":
        return "Which account did it go into?" if kind == "income" else "Which account did you pay from?"
    return "Which category fits best?"


def options_for(user: User, fields: dict, pending_field: str | None, categories: list[Category],
                accounts: list[Account]) -> list[dict]:
    """The user's own valid choices for the open question (empty when it is free text). Always ends with a way to skip."""
    if pending_field == "account_id":
        active = [a for a in accounts if not a.is_archived]
        narrowed = set(f.account_candidates(fields))
        pool = [a for a in active if str(a.id) in narrowed] or active
        return [{"id": str(a.id), "label": a.name} for a in pool[:MAX_OPTIONS]] + [{"id": "", "label": "No account"}]
    if pending_field == "category_id":
        kind = f.value(fields, "transaction_type")
        usable = [c for c in categories if not c.is_archived and c.kind == kind]
        usage = _category_usage(user)
        usable.sort(key=lambda c: (-usage.get(str(c.id), 0), c.name.lower()))
        return [{"id": str(c.id), "label": c.name} for c in usable[:MAX_OPTIONS]] + [{"id": "", "label": "Uncategorised"}]
    return []


def _category_usage(user: User) -> Counter:
    rows = db.session.execute(
        select(Transaction.category_id, func.count()).where(Transaction.user_id == user.id, Transaction.category_id.is_not(None))
        .group_by(Transaction.category_id)
    )
    return Counter({str(cid): count for cid, count in rows})


def answer_option(options: list[dict], text: str) -> dict | None:
    """Match a short reply (a tapped option, or the name typed) to one of the offered choices, or to 'skip'."""
    wanted = " ".join(text.lower().split()).strip(" .!")
    if not wanted:
        return None
    if wanted in SKIP_WORDS:
        return next((o for o in options if o["id"] == ""), None)
    exact = [o for o in options if o["label"].lower() == wanted]
    if len(exact) == 1:
        return exact[0]
    partial = [o for o in options if o["id"] and wanted in o["label"].lower() and len(wanted) >= 3]
    return partial[0] if len(partial) == 1 else None
