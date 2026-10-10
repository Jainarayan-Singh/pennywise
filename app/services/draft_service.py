"""Expense drafts: assemble a transaction from natural language over several turns, then confirm.

State machine: needs_clarification -> ready_for_review -> saved, with cancelled / expired as exits.
A draft becomes a transaction only through `confirm_draft`, which reuses the normal transaction
validation and is idempotent per draft, so double clicks and retries cannot save twice.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import delete, select

from app.config import Settings
from app.extensions import db
from app.integrations.ai.base import AIProvider
from app.models import ExpenseDraft, User
from app.models.ai import ACTIVE_DRAFT_STATUSES
from app.models.base import as_utc, utcnow
from app.models.finance import PAYMENT_METHODS
from app.services import catalog_service, expense_intent as intent, transaction_service
from app.services.audit_service import record_event
from app.services.money import format_amount, parse_amount
from app.utils.errors import ApiError, ValidationFailed

REQUIRED_ORDER = ("amount", "transaction_type", "transaction_date")
FIELD_LABELS = (
    ("transaction_type", "Type"), ("amount", "Amount"), ("transaction_date", "Date"),
    ("category_id", "Category"), ("account_id", "Account"), ("payment_method", "Payment method"),
    ("merchant", "Merchant"), ("description", "Description"),
)
EDITABLE_FIELDS = {key for key, _ in FIELD_LABELS}
_CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}
_KEEP_CLOSED_FOR = timedelta(hours=24)


# --- field bookkeeping ----------------------------------------------------------------------


def _put(fields: dict, key: str, value, source: str, note: str | None = None) -> None:
    fields[key] = {"value": value, "source": source, **({"note": note} if note else {})}


def _value(fields: dict, key: str):
    entry = fields.get(key)
    return entry["value"] if entry else None


def _money_label(fields: dict) -> str:
    amount, currency = Decimal(_value(fields, "amount")), _value(fields, "currency") or ""
    text = f"{amount:f}".rstrip("0").rstrip(".") if amount == amount.to_integral() else f"{amount:.2f}"
    symbol = _CURRENCY_SYMBOLS.get(currency)
    return f"{symbol}{text}" if symbol else f"{currency} {text}".strip()


def _default_question(fields: dict, missing: str) -> str:
    if missing == "amount":
        return "How much was it?"
    if missing == "transaction_type":
        return "Was this an expense or income?"
    verb = {"expense": "spend", "income": "receive"}.get(_value(fields, "transaction_type"))
    return f"On which date did you {verb} {_money_label(fields)}?" if verb else "On which date was this?"


def _lookups(user: User):
    return catalog_service.list_categories(user, scope="all"), catalog_service.list_accounts(user, scope="all")


def _ensure_currency(user: User, fields: dict, accounts: list) -> None:
    if _value(fields, "currency"):
        return
    account_id = _value(fields, "account_id")
    account = next((a for a in accounts if str(a.id) == account_id), None)
    _put(fields, "currency", account.currency if account else user.preferences.currency, "default")


def _clean(value: str | None, limit: int) -> str | None:
    text = " ".join((value or "").split())
    return text[:limit] or None


# --- merging what the user said -------------------------------------------------------------


def _apply_extraction(user: User, fields: dict, ex: intent.Extraction) -> tuple[str | None, str | None]:
    """Merge an extraction into `fields`. Returns (question, field) when something needs re-asking."""
    today = transaction_service.user_today(user)
    day_first = user.preferences.date_format.upper().startswith("D")
    categories, accounts = _lookups(user)
    problem: tuple[str, str] | None = None

    if ex.transaction_type != "unknown":
        _put(fields, "transaction_type", ex.transaction_type, "explicit")

    if ex.amount_text:
        amount = intent.parse_spoken_amount(ex.amount_text)
        if amount is not None:
            _put(fields, "amount", format_amount(amount), "explicit")
            if code := intent.detect_currency(ex.amount_text) or intent.detect_currency(ex.currency_text):
                _put(fields, "currency", code, "explicit")
        else:
            problem = (f"I couldn't read “{ex.amount_text[:40]}” as an amount. How much was it?", "amount")
    elif ex.currency_text and (code := intent.detect_currency(ex.currency_text)):
        _put(fields, "currency", code, "explicit")

    if ex.date_text:
        resolution = intent.resolve_date_phrase(ex.date_text, today, day_first=day_first)
        phrase = ex.date_text[:40]
        if resolution.status == "resolved":
            _put(fields, "transaction_date", resolution.value.isoformat(), "rule", f"from “{phrase}”")
        elif problem is None:
            reasons = {
                "future": "That date is in the future. On which date was it?",
                "ambiguous": f"Which exact date do you mean by “{phrase}”?",
                "unparsed": f"I couldn't work out a date from “{phrase}”. Which date was it?",
            }
            problem = (reasons[resolution.status], "transaction_date")

    if hint := ex.category_hint:
        kind = _value(fields, "transaction_type")
        existing = fields.get("category_id")
        category = None if existing and existing["source"] == "explicit" else intent.match_category(hint, categories, kind)
        if category:
            _put(fields, "category_id", str(category.id), "inferred", f"from “{hint[:30]}”")
    if ex.account_hint and (account := intent.match_by_name(ex.account_hint, [a for a in accounts if not a.is_archived])):
        _put(fields, "account_id", str(account.id), "explicit")
        if not (fields.get("currency") and fields["currency"]["source"] == "explicit"):
            fields.pop("currency", None)  # re-derive from the account below
    if ex.payment_method in PAYMENT_METHODS:
        _put(fields, "payment_method", ex.payment_method, "explicit")
    for key, limit, raw in (("merchant", 120, ex.merchant), ("description", 255, ex.description)):
        if cleaned := _clean(raw, limit):
            _put(fields, key, cleaned, "explicit")

    _ensure_currency(user, fields, accounts)
    return problem if problem else (None, None)


def _advance(draft: ExpenseDraft, question: str | None = None, field: str | None = None) -> None:
    if question and field:  # a correction we couldn't apply must be asked about, even if an older value exists
        draft.status, draft.pending_field, draft.question = "needs_clarification", field, question
        return
    missing = [key for key in REQUIRED_ORDER if not _value(draft.fields, key)]
    if not missing:
        draft.status, draft.pending_field, draft.question = "ready_for_review", None, None
        return
    draft.status, draft.pending_field = "needs_clarification", missing[0]
    draft.question = _default_question(draft.fields, missing[0])


def _answer_directly(pending: str | None, text: str, user: User) -> intent.Extraction | None:
    """Plain answers to the question just asked are parsed locally: no AI call, no quota used."""
    if pending is None or len(text.split()) > 6:
        return None
    if pending == "amount" and intent.parse_spoken_amount(text) is not None:
        return intent.Extraction(amount_text=text)
    if pending == "transaction_type" and (kind := intent.detect_type(text)):
        return intent.Extraction(transaction_type=kind)
    if pending == "transaction_date":
        day_first = user.preferences.date_format.upper().startswith("D")
        if intent.resolve_date_phrase(text, transaction_service.user_today(user), day_first=day_first).status != "unparsed":
            return intent.Extraction(date_text=text)
    return None


# --- lifecycle ------------------------------------------------------------------------------


def _touch(draft: ExpenseDraft, settings: Settings) -> None:
    draft.expires_at = utcnow() + timedelta(minutes=settings.ai.draft_ttl_minutes)
    draft.turn_count += 1


def create_draft(user: User, text: str, provider: AIProvider, settings: Settings, *, source: str = "text") -> ExpenseDraft:
    text = intent.clean_user_text(text)
    extraction = intent.extract(provider, text)  # raises AIError before anything is stored
    db.session.execute(delete(ExpenseDraft).where(ExpenseDraft.expires_at < utcnow() - _KEEP_CLOSED_FOR))

    draft = ExpenseDraft(user_id=user.id, status="needs_clarification", input_source=source, fields={}, turn_count=0,
                         expires_at=utcnow())
    fields: dict = {}
    question, field = _apply_extraction(user, fields, extraction)
    draft.fields = fields
    _advance(draft, question, field)
    _touch(draft, settings)
    db.session.add(draft)
    db.session.commit()
    record_event("ai.draft_created", user.id, draft_id=str(draft.id))
    return draft


def _load(user: User, draft_id: uuid.UUID, *, lock: bool = False) -> ExpenseDraft:
    stmt = select(ExpenseDraft).where(ExpenseDraft.id == draft_id, ExpenseDraft.user_id == user.id)
    draft = db.session.execute(stmt.with_for_update() if lock else stmt).scalar_one_or_none()
    if draft is None:
        raise ApiError("Draft not found.", status_code=404, code="not_found")
    if draft.status in ACTIVE_DRAFT_STATUSES and as_utc(draft.expires_at) <= utcnow():
        draft.status, draft.pending_field, draft.question = "expired", None, None
        db.session.commit()
    return draft


def get_draft(user: User, draft_id: uuid.UUID) -> ExpenseDraft:
    return _load(user, draft_id)


def _require_active(draft: ExpenseDraft) -> None:
    if draft.status == "expired":
        raise ApiError("This draft expired. Start again.", status_code=410, code="draft_expired")
    if draft.status not in ACTIVE_DRAFT_STATUSES:
        raise ApiError(f"This draft is already {draft.status}.", status_code=409, code="draft_closed")


def add_message(user: User, draft_id: uuid.UUID, text: str, provider: AIProvider, settings: Settings) -> ExpenseDraft:
    draft = _load(user, draft_id)
    _require_active(draft)
    text = intent.clean_user_text(text)

    extraction = _answer_directly(draft.pending_field, text, user)
    if extraction is None:
        context = {key: _value(draft.fields, key) for key in ("amount", "currency", "transaction_type", "transaction_date")}
        extraction = intent.extract(provider, text, current_draft=context, question=draft.question)

    fields = dict(draft.fields)
    question, field = _apply_extraction(user, fields, extraction)
    draft.fields = fields
    _advance(draft, question, field)
    _touch(draft, settings)
    db.session.commit()
    return draft


def update_fields(user: User, draft_id: uuid.UUID, patch: dict, settings: Settings) -> ExpenseDraft:
    """Direct edits from the review form. Validated like manual entry; no AI involved."""
    draft = _load(user, draft_id)
    _require_active(draft)
    unknown = set(patch) - EDITABLE_FIELDS
    if unknown:
        raise ValidationFailed("Some fields are invalid.", details={name: "Not an editable field." for name in unknown})

    fields = dict(draft.fields)
    today = transaction_service.user_today(user)
    for key, raw in patch.items():
        if key == "amount":
            _put(fields, key, format_amount(parse_amount(raw)), "explicit")
        elif key == "transaction_type":
            if raw not in ("expense", "income"):
                raise ValidationFailed("Some fields are invalid.", details={key: "Must be expense or income."})
            _put(fields, key, raw, "explicit")
        elif key == "transaction_date":
            parsed = transaction_service.parse_iso_date(raw, key)
            if parsed > today or parsed < transaction_service.MIN_DATE:
                raise ValidationFailed("Some fields are invalid.", details={key: "Pick a date that is not in the future."})
            _put(fields, key, parsed.isoformat(), "explicit")
        elif key in ("category_id", "account_id"):
            if raw in (None, ""):
                fields.pop(key, None)
                continue
            getter = catalog_service.get_category if key == "category_id" else catalog_service.get_account
            try:
                row = getter(user, uuid.UUID(str(raw)))
            except (ApiError, ValueError):
                raise ValidationFailed("Some fields are invalid.", details={key: "Unknown value."}) from None
            _put(fields, key, str(row.id), "explicit")
            if key == "account_id" and (fields.get("currency") or {}).get("source") != "explicit":
                fields.pop("currency", None)
        elif key == "payment_method":
            if raw in (None, ""):
                fields.pop(key, None)
            elif raw in PAYMENT_METHODS:
                _put(fields, key, raw, "explicit")
            else:
                raise ValidationFailed("Some fields are invalid.", details={key: "Unknown payment method."})
        else:  # merchant, description
            cleaned = _clean(raw if isinstance(raw, str) else None, 120 if key == "merchant" else 255)
            if cleaned:
                _put(fields, key, cleaned, "explicit")
            else:
                fields.pop(key, None)

    _categories, accounts = _lookups(user)
    _ensure_currency(user, fields, accounts)
    draft.fields = fields
    _advance(draft)
    _touch(draft, settings)
    db.session.commit()
    return draft


def cancel_draft(user: User, draft_id: uuid.UUID) -> None:
    draft = _load(user, draft_id)
    if draft.status == "saved":
        raise ApiError("This draft was already saved as a transaction.", status_code=409, code="draft_closed")
    if draft.status in ACTIVE_DRAFT_STATUSES:
        draft.status, draft.pending_field, draft.question = "cancelled", None, None
        db.session.commit()


def confirm_draft(user: User, draft_id: uuid.UUID):
    """Save the draft as a transaction. Returns (draft, transaction, created)."""
    draft = _load(user, draft_id, lock=True)
    if draft.status == "saved" and draft.saved_transaction_id:
        return draft, transaction_service.get_transaction(user, draft.saved_transaction_id), False
    if draft.status == "expired":
        raise ApiError("This draft expired. Start again.", status_code=410, code="draft_expired")
    if draft.status != "ready_for_review":
        raise ApiError("Answer the open question before saving.", status_code=409, code="draft_not_ready")

    fields = draft.fields
    data = {
        "type": _value(fields, "transaction_type"),
        "amount": _value(fields, "amount"),
        "currency": _value(fields, "currency"),
        "transaction_date": _value(fields, "transaction_date"),
    }
    for key in ("category_id", "account_id"):
        if _value(fields, key):
            data[key] = uuid.UUID(_value(fields, key))
    for key in ("payment_method", "merchant", "description"):
        if _value(fields, key):
            data[key] = _value(fields, key)

    # The draft id is the idempotency key: any retry returns the transaction that was already created.
    txn, created, _duplicates = transaction_service.create_transaction(
        user, data, set(data), idempotency_key=f"draft-{draft.id.hex}",
        source="voice" if draft.input_source == "voice" else "ai",
    )
    draft = _load(user, draft_id, lock=True)
    draft.status, draft.pending_field, draft.question = "saved", None, None
    draft.saved_transaction_id = txn.id
    db.session.commit()
    record_event("ai.draft_saved", user.id, draft_id=str(draft.id), transaction_id=str(txn.id))
    return draft, txn, created


# --- presentation ---------------------------------------------------------------------------


def serialize(user: User, draft: ExpenseDraft) -> dict:
    categories, accounts = _lookups(user)
    names = {str(c.id): c.name for c in categories} | {str(a.id): a.name for a in accounts}
    rows = []
    for key, label in FIELD_LABELS:
        entry = draft.fields.get(key)
        required = key in REQUIRED_ORDER
        rows.append({
            "key": key,
            "label": label,
            "value": entry["value"] if entry else None,
            "display": names.get(entry["value"]) if entry and key in ("category_id", "account_id") else None,
            "source": entry["source"] if entry else ("missing" if required else "unset"),
            "note": entry.get("note") if entry else None,
        })
    return {
        "id": str(draft.id),
        "status": draft.status,
        "question": draft.question,
        "pending_field": draft.pending_field,
        "currency": _value(draft.fields, "currency") or user.preferences.currency,
        "fields": rows,
        "expires_at": as_utc(draft.expires_at).isoformat(),
        "transaction_id": str(draft.saved_transaction_id) if draft.saved_transaction_id else None,
    }
