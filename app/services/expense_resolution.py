"""Resolution: decide the category, account, type and payment method of a draft from what is known.

Nothing here talks to the AI. The model may only *propose* (a phrase, or a name copied from the user's own lists);
every proposal is checked against the user's real categories and accounts before it is used.

Order of trust for each field:
  1. what the user explicitly said or chose (never overwritten by a guess)
  2. a name proposed by the model that exactly matches one of the user's own items
  3. fixed rules over the wording (synonyms for categories, distinctive words for account names)
  4. the user's own history (the same merchant, or the same category, always went to the same place)
  5. otherwise the field stays unresolved, and the clarification stage decides whether to ask

Every inferred value carries a note saying where it came from, so the review can show it as a suggestion.
"""
from __future__ import annotations

import re
import uuid
from collections import Counter

from sqlalchemy import func, select

from app.extensions import db
from app.models import Account, Category, Transaction, User
from app.services import expense_fields as f, expense_intent as intent

# Words that appear in many account names and so say nothing about which account was meant.
_GENERIC_ACCOUNT_WORDS = {
    "account", "accounts", "acc", "bank", "savings", "saving", "current", "card", "credit", "debit", "wallet",
    "cash", "upi", "my", "the", "and", "money", "main", "personal",
}
# The account types a payment method points at (a card payment points at a card account, and so on).
_ACCOUNT_TYPES_FOR_METHOD = {
    "cash": ("cash",), "card": ("card",), "upi": ("bank", "wallet"), "bank_transfer": ("bank",), "cheque": ("bank",),
}
_PAYMENT_METHOD_FOR_ACCOUNT_TYPE = {"cash": "cash", "card": "card"}
_HISTORY_DEPTH = 5
_HABIT_WINDOW, _HABIT_MIN, _HABIT_SHARE = 20, 5, 0.8  # what counts as a habitual account


def resolve(user: User, fields: dict, extraction: intent.Extraction, raw_text: str,
            categories: list[Category], accounts: list[Account]) -> None:
    """Fill in whatever can be established after an extraction has been merged. Mutates `fields`."""
    active_accounts = [a for a in accounts if not a.is_archived]
    _resolve_type(fields, raw_text)
    _resolve_category(user, fields, extraction, raw_text, categories)
    _resolve_account(user, fields, extraction, raw_text, active_accounts)
    _resolve_payment_method(fields, active_accounts)




def _resolve_type(fields: dict, raw_text: str) -> None:
    if f.value(fields, "transaction_type"):
        return
    if kind := intent.detect_type(raw_text):
        f.put(fields, "transaction_type", kind, "inferred", "from your wording")




def _by_name(items, name: str | None):
    wanted = " ".join((name or "").lower().split())
    return next((item for item in items if item.name.lower() == wanted), None) if wanted else None


def _words(text: str | None) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _resolve_category(user: User, fields: dict, ex: intent.Extraction, raw_text: str, categories: list[Category]) -> None:
    if f.is_explicit(fields, "category_id"):
        return
    kind = f.value(fields, "transaction_type")
    candidates = [c for c in categories if not c.is_archived and (kind is None or c.kind == kind)]

    chosen, why, source = None, None, "inferred"
    if named := _by_name(candidates, ex.category_choice):
        chosen = named
        if _words(named.name) <= _words(raw_text):  # the user literally said the category's name
            source, why = "explicit", None
        else:
            why = "from your description"
    if chosen is None:  # the user's own purpose words first (what it was for), then their history with the merchant
        for hint in (ex.category_hint, ex.description):
            if match := intent.match_category(hint, categories, kind):
                chosen, why = match, f"from “{(hint or '')[:30]}”"
                break
    if chosen is None and (merchant := f.value(fields, "merchant") or ex.merchant):
        chosen, why = _category_from_history(user, merchant, kind), f"as with earlier {merchant[:30]}"
    if chosen is None:  # last: any purpose word anywhere in what they wrote
        for hint in (ex.merchant, raw_text):
            if match := intent.match_category(hint, categories, kind):
                chosen, why = match, f"from “{(hint or '')[:30]}”"
                break
    if chosen is None:
        return

    f.put(fields, "category_id", str(chosen.id), source, why)
    if kind is None:  # "Salary" or "Freelance" settles the type too, but only as an inference
        f.put(fields, "transaction_type", chosen.kind, "inferred", "from the category")


def _category_from_history(user: User, merchant: str, kind: str | None) -> Category | None:
    """The category of the same merchant, when each of the last few payments there used the same one."""
    stmt = (
        select(Transaction.category_id)
        .where(Transaction.user_id == user.id, func.lower(Transaction.merchant) == merchant.lower(),
               Transaction.category_id.is_not(None))
        .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
        .limit(_HISTORY_DEPTH)
    )
    ids = {row for row in db.session.execute(stmt).scalars()}
    if len(ids) != 1:
        return None
    category = db.session.get(Category, ids.pop())
    ok = category is not None and category.user_id == user.id and not category.is_archived
    return category if ok and (kind is None or category.kind == kind) else None




def accounts_mentioned(text: str | None, accounts: list[Account]) -> list[Account]:
    """Accounts the wording refers to: by full name, or by a distinctive word of the name ("HDFC" for "HDFC Savings")."""
    lowered = (text or "").lower()
    words = _words(lowered)
    full = [a for a in accounts if re.search(rf"(?<![a-z0-9]){re.escape(a.name.lower())}(?![a-z0-9])", lowered)]
    if full:
        return full
    return [
        a for a in accounts
        if any(len(token) >= 3 and token not in _GENERIC_ACCOUNT_WORDS and token in words for token in _words(a.name))
    ]


def _resolve_account(user: User, fields: dict, ex: intent.Extraction, raw_text: str, accounts: list[Account]) -> None:
    f.set_account_candidates(fields, [])
    f.set_unmatched_account(fields, None)
    if f.is_explicit(fields, "account_id") or not accounts:
        return

    named = _by_name(accounts, ex.account_choice) or intent.match_by_name(ex.account_hint, accounts)
    mentioned = [named] if named else accounts_mentioned(f"{ex.account_hint or ''} {raw_text}", accounts)
    if len(mentioned) == 1:
        f.put(fields, "account_id", str(mentioned[0].id), "explicit")
        _currency_follows_account(fields)
        return
    if len(mentioned) > 1:  # "HDFC" fits two accounts: ask, and offer only those two
        f.set_account_candidates(fields, [str(a.id) for a in mentioned])
        return

    if ex.account_hint and ex.account_hint.strip():  # they named an account that is not one of theirs: ask, don't guess
        f.set_unmatched_account(fields, ex.account_hint)
        return
    if f.value(fields, "account_id"):
        return  # an earlier inference stands until something better arrives
    if account := _account_for_payment_method(fields, accounts):
        f.put(fields, "account_id", str(account.id), "inferred", f"your only {account.account_type} account")
    elif len(accounts) == 1:
        f.put(fields, "account_id", str(accounts[0].id), "inferred", "your only account")
    elif account := _account_from_history(user, fields, accounts):
        f.put(fields, "account_id", str(account.id), "inferred", "your usual account")
    if f.value(fields, "account_id"):
        _currency_follows_account(fields)


def _currency_follows_account(fields: dict) -> None:
    if f.source(fields, "currency") != "explicit":
        fields.pop("currency", None)  # draft_service re-derives it from the account


def _account_for_payment_method(fields: dict, accounts: list[Account]) -> Account | None:
    types = _ACCOUNT_TYPES_FOR_METHOD.get(f.value(fields, "payment_method") or "")
    matching = [a for a in accounts if types and a.account_type in types]
    return matching[0] if len(matching) == 1 else None


def _recent_accounts(user: User, *scope, limit: int) -> list[str]:
    stmt = (
        select(Transaction.account_id)
        .where(Transaction.user_id == user.id, Transaction.account_id.is_not(None), *scope)
        .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
        .limit(limit)
    )
    return [str(row) for row in db.session.execute(stmt).scalars()]


def _account_from_history(user: User, fields: dict, accounts: list[Account]) -> Account | None:
    """An account the user's own history establishes, from the narrowest evidence to the widest:

    1. every recent payment to the same merchant (or in the same category) used it, at least twice;
    2. otherwise an established habit: at least five of the last twenty payments, and 80% or more of them, used it.
    An even split is not a habit, so the user is asked.
    """
    merchant, category_id = f.value(fields, "merchant"), f.value(fields, "category_id")
    scopes = []
    if merchant:
        scopes.append(func.lower(Transaction.merchant) == merchant.lower())
    if category_id:
        scopes.append(Transaction.category_id == uuid.UUID(category_id))
    for scope in scopes:
        used = Counter(_recent_accounts(user, scope, limit=_HISTORY_DEPTH))
        if len(used) == 1 and sum(used.values()) >= 2:
            return next((a for a in accounts if str(a.id) in used), None)

    recent = _recent_accounts(user, limit=_HABIT_WINDOW)
    if len(recent) >= _HABIT_MIN:
        top, count = Counter(recent).most_common(1)[0]
        if count / len(recent) >= _HABIT_SHARE:
            return next((a for a in accounts if str(a.id) == top), None)
    return None




def _resolve_payment_method(fields: dict, accounts: list[Account]) -> None:
    if f.value(fields, "payment_method") or not f.value(fields, "account_id"):
        return
    account = next((a for a in accounts if str(a.id) == f.value(fields, "account_id")), None)
    if account and (method := _PAYMENT_METHOD_FOR_ACCOUNT_TYPE.get(account.account_type)):
        f.put(fields, "payment_method", method, "inferred", f"from the {account.account_type} account")
