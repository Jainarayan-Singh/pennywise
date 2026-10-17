"""Expense drafts: assemble a transaction from natural language over several turns, then confirm.

This module orchestrates; each stage lives in its own module:

  expense_intent         extraction. The model returns phrases and proposals; amounts and dates are parsed by rules.
  expense_resolution     category, account, type, payment method: explicit words first, then the user's own data.
  expense_validation     every value is re-checked against the transaction rules and the user's own lists.
  expense_clarification  what is missing or ambiguous, and the one question to ask next.
  draft_service (here)   the draft's lifecycle: create, add a message, edit, cancel, confirm.

State machine: needs_clarification -> ready_for_review -> saved, with cancelled / expired as exits.
A draft becomes a transaction only through `confirm_draft`, which reuses the normal transaction validation and is
idempotent per draft, so double clicks and retries cannot save twice.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import delete, select

from app.config import Settings
from app.extensions import db
from app.integrations.ai.base import AIProvider
from app.models import ExpenseDraft, User
from app.models.ai import ACTIVE_DRAFT_STATUSES
from app.models.base import as_utc, utcnow
from app.models.finance import PAYMENT_METHODS
from app.services import (
    catalog_service, expense_clarification as clarify, expense_fields as f, expense_intent as intent,
    expense_resolution as resolution, expense_validation as validation, transaction_service,
)
from app.services.audit_service import record_event
from app.services.money import format_amount, parse_amount
from app.utils.errors import ApiError, ValidationFailed

FIELD_LABELS = f.FIELD_LABELS
EDITABLE_FIELDS = f.EDITABLE_FIELDS
_KEEP_CLOSED_FOR = timedelta(hours=24)


def _lookups(user: User):
    return catalog_service.list_categories(user, scope="all"), catalog_service.list_accounts(user, scope="all")


def _ai_options(categories, accounts) -> dict:
    """Names of the user's own active categories and accounts, offered to the model as the only valid choices."""
    return {
        "expense": [c.name for c in categories if not c.is_archived and c.kind == "expense"],
        "income": [c.name for c in categories if not c.is_archived and c.kind == "income"],
        "accounts": [a.name for a in accounts if not a.is_archived],
    }


def _ensure_currency(user: User, fields: dict, accounts: list) -> None:
    """Documented default: the chosen account's currency, otherwise the user's preferred currency."""
    if f.value(fields, "currency"):
        return
    account = next((a for a in accounts if str(a.id) == f.value(fields, "account_id")), None)
    f.put(fields, "currency", account.currency if account else user.preferences.currency, "default")




def _merge_explicit(user: User, fields: dict, ex: intent.Extraction) -> tuple[str, str] | None:
    """Merge the facts the user stated (type, amount, currency, date, payment method, merchant, purpose).

    Returns (question, field) for a stated value that could not be understood, so it is asked about
    instead of silently dropped.
    """
    today = transaction_service.user_today(user)
    day_first = user.preferences.date_format.upper().startswith("D")
    problem: tuple[str, str] | None = None

    if ex.transaction_type != "unknown":
        f.put(fields, "transaction_type", ex.transaction_type, "explicit")

    if ex.amount_text:
        amount = intent.parse_spoken_amount(ex.amount_text)
        if amount is not None:
            f.put(fields, "amount", format_amount(amount), "explicit")
            if code := intent.detect_currency(ex.amount_text) or intent.detect_currency(ex.currency_text):
                f.put(fields, "currency", code, "explicit")
        else:
            problem = (f"I couldn't read “{ex.amount_text[:40]}” as an amount. How much was it?", "amount")
    elif ex.currency_text and (code := intent.detect_currency(ex.currency_text)):
        f.put(fields, "currency", code, "explicit")

    if ex.date_text:
        resolved = intent.resolve_date_phrase(ex.date_text, today, day_first=day_first)
        phrase = ex.date_text[:40]
        if resolved.status == "resolved":
            f.put(fields, "transaction_date", resolved.value.isoformat(), "rule", f"from “{phrase}”")
        elif problem is None:
            reasons = {
                "future": "That date is in the future. On which date was it?",
                "ambiguous": f"Which exact date do you mean by “{phrase}”?",
                "unparsed": f"I couldn't work out a date from “{phrase}”. Which date was it?",
            }
            problem = (reasons[resolved.status], "transaction_date")

    if ex.payment_method in PAYMENT_METHODS:
        f.put(fields, "payment_method", ex.payment_method, "explicit")
    for key, limit, raw in (("merchant", 120, ex.merchant), ("description", 255, ex.description)):
        if cleaned := f.clean_text(raw, limit):
            f.put(fields, key, cleaned, "explicit")
    return problem


def _run_pipeline(user: User, draft: ExpenseDraft, fields: dict, extraction: intent.Extraction | None,
                  raw_text: str = "") -> None:
    """Merge, resolve, validate, then decide the next step, and store the outcome on the draft."""
    categories, accounts = _lookups(user)
    problem = None
    if extraction is not None:
        problem = _merge_explicit(user, fields, extraction)
        resolution.resolve(user, fields, extraction, raw_text, categories, accounts)
    problems = validation.sanitize(user, fields, categories, accounts)
    _ensure_currency(user, fields, accounts)
    step = clarify.next_step(user, fields, problems, categories, accounts, extra_problem=problem)
    draft.fields = fields
    draft.status, draft.pending_field, draft.question = step.status, step.pending_field, step.question


def _direct_answer(user: User, fields: dict, pending: str | None, text: str) -> intent.Extraction | bool | None:
    """Plain answers to the question just asked are handled locally: no AI call, no quota used.

    Returns an Extraction to merge, True when a tapped or typed choice was applied to `fields`, or None when the
    message needs the model.
    """
    if pending is None:
        return None
    if pending in f.ASKED_ONCE:
        categories, accounts = _lookups(user)
        options = clarify.options_for(user, fields, pending, categories, accounts)
        choice = clarify.answer_option(options, text)
        if choice is None:
            return None
        if choice["id"]:
            f.put(fields, pending, choice["id"], "explicit")
            if pending == "account_id" and f.source(fields, "currency") != "explicit":
                fields.pop("currency", None)
        return True
    if len(text.split()) > 6:
        return None
    first = pending.split(",")[0]
    if first == "amount" and intent.parse_spoken_amount(text) is not None:
        return intent.Extraction(amount_text=text)
    if pending == "transaction_type" and (kind := intent.detect_type(text)):
        return intent.Extraction(transaction_type=kind)
    if pending == "transaction_date":
        day_first = user.preferences.date_format.upper().startswith("D")
        if intent.resolve_date_phrase(text, transaction_service.user_today(user), day_first=day_first).status != "unparsed":
            return intent.Extraction(date_text=text)
    return None




def _touch(draft: ExpenseDraft, settings: Settings) -> None:
    draft.expires_at = utcnow() + timedelta(minutes=settings.ai.draft_ttl_minutes)
    draft.turn_count += 1


def create_draft(user: User, text: str, provider: AIProvider, settings: Settings, *, source: str = "text") -> ExpenseDraft:
    text = intent.clean_user_text(text)
    categories, accounts = _lookups(user)
    extraction = intent.extract(provider, text, options=_ai_options(categories, accounts))  # raises AIError before anything is stored
    db.session.execute(delete(ExpenseDraft).where(ExpenseDraft.expires_at < utcnow() - _KEEP_CLOSED_FOR))

    draft = ExpenseDraft(user_id=user.id, status="needs_clarification", input_source=source, fields={}, turn_count=0,
                         expires_at=utcnow())
    _run_pipeline(user, draft, {}, extraction, text)
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
    fields = dict(draft.fields)

    answer = _direct_answer(user, fields, draft.pending_field, text)
    extraction = answer if isinstance(answer, intent.Extraction) else None
    if answer is None:
        categories, accounts = _lookups(user)
        context = {key: f.value(fields, key) for key in ("amount", "currency", "transaction_type", "transaction_date")}
        extraction = intent.extract(provider, text, current_draft=context, question=draft.question,
                                    options=_ai_options(categories, accounts))

    _run_pipeline(user, draft, fields, extraction, text)
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
            f.put(fields, key, format_amount(parse_amount(raw)), "explicit")
        elif key == "transaction_type":
            if raw not in ("expense", "income"):
                raise ValidationFailed("Some fields are invalid.", details={key: "Must be expense or income."})
            f.put(fields, key, raw, "explicit")
        elif key == "transaction_date":
            parsed = transaction_service.parse_iso_date(raw, key)
            if parsed > today or parsed < transaction_service.MIN_DATE:
                raise ValidationFailed("Some fields are invalid.", details={key: "Pick a date that is not in the future."})
            f.put(fields, key, parsed.isoformat(), "explicit")
        elif key in ("category_id", "account_id"):
            if not f.times_asked(fields, key):
                f.mark_asked(fields, key)  # a deliberate choice, even "none", is final
            if raw in (None, ""):
                fields.pop(key, None)
                continue
            getter = catalog_service.get_category if key == "category_id" else catalog_service.get_account
            try:
                row = getter(user, uuid.UUID(str(raw)))
            except (ApiError, ValueError):
                raise ValidationFailed("Some fields are invalid.", details={key: "Unknown value."}) from None
            f.put(fields, key, str(row.id), "explicit")
            if key == "account_id" and f.source(fields, "currency") != "explicit":
                fields.pop("currency", None)
        elif key == "payment_method":
            if raw in (None, ""):
                fields.pop(key, None)
            elif raw in PAYMENT_METHODS:
                f.put(fields, key, raw, "explicit")
            else:
                raise ValidationFailed("Some fields are invalid.", details={key: "Unknown payment method."})
        else:  # merchant, description
            cleaned = f.clean_text(raw if isinstance(raw, str) else None, 120 if key == "merchant" else 255)
            if cleaned:
                f.put(fields, key, cleaned, "explicit")
            else:
                fields.pop(key, None)

    _run_pipeline(user, draft, fields, None)
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

    # The categories and accounts may have changed since the draft was prepared: check once more before saving.
    categories, accounts = _lookups(user)
    fields = dict(draft.fields)
    reviewed = {key: f.value(fields, key) for key in ("category_id", "account_id") if f.value(fields, key)}
    validation.sanitize(user, fields, categories, accounts)
    changed = any(f.value(fields, key) != value for key, value in reviewed.items())
    if changed or any(not f.value(fields, key) for key in f.REQUIRED_ORDER):
        _run_pipeline(user, draft, fields, None)
        db.session.commit()
        raise ApiError("Some details changed since you reviewed this draft. Check it again before saving.",
                       status_code=409, code="draft_changed")
    draft.fields = fields

    data = {
        "type": f.value(fields, "transaction_type"),
        "amount": f.value(fields, "amount"),
        "currency": f.value(fields, "currency"),
        "transaction_date": f.value(fields, "transaction_date"),
    }
    for key in ("category_id", "account_id"):
        if f.value(fields, key):
            data[key] = uuid.UUID(f.value(fields, key))
    for key in ("payment_method", "merchant", "description"):
        if f.value(fields, key):
            data[key] = f.value(fields, key)

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



_KNOWN_SOURCES = {"explicit", "rule"}


def _state_of(draft: ExpenseDraft, key: str) -> str:
    """known / inferred / missing / ambiguous / unset: the four states of the pipeline, plus 'optional and empty'."""
    entry = draft.fields.get(key)
    if entry:
        return "known" if entry["source"] in _KNOWN_SOURCES else "inferred"
    pending = (draft.pending_field or "").split(",")
    if key in pending:
        return "missing" if key in f.REQUIRED_ORDER else "ambiguous"
    return "missing" if key in f.REQUIRED_ORDER else "unset"


def serialize(user: User, draft: ExpenseDraft) -> dict:
    categories, accounts = _lookups(user)
    names = {str(c.id): c.name for c in categories} | {str(a.id): a.name for a in accounts}
    rows = []
    for key, label in FIELD_LABELS:
        entry = draft.fields.get(key)
        required = key in f.REQUIRED_ORDER
        rows.append({
            "key": key,
            "label": label,
            "value": entry["value"] if entry else None,
            "display": names.get(entry["value"]) if entry and key in ("category_id", "account_id") else None,
            "source": entry["source"] if entry else ("missing" if required else "unset"),
            "state": _state_of(draft, key),
            "note": entry.get("note") if entry else None,
        })
    pending = (draft.pending_field or "").split(",")[0] or None
    return {
        "id": str(draft.id),
        "status": draft.status,
        "question": draft.question,
        "pending_field": draft.pending_field,
        "options": clarify.options_for(user, draft.fields, pending, categories, accounts) if draft.status == "needs_clarification" else [],
        "currency": f.value(draft.fields, "currency") or user.preferences.currency,
        "fields": rows,
        "expires_at": as_utc(draft.expires_at).isoformat(),
        "transaction_id": str(draft.saved_transaction_id) if draft.saved_transaction_id else None,
    }
