"""Income/expense transactions: validation, ownership, filtering, summaries.

Every query is scoped by user_id here, never in the route or the browser.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import Transaction, User
from app.models.finance import PAYMENT_METHODS, TRANSACTION_TYPES
from app.services import catalog_service
from app.services.audit_service import record_event
from app.services.money import CENT, format_amount, normalize_currency, parse_amount
from app.utils.errors import ApiError, ValidationFailed

MIN_DATE = date(2000, 1, 1)
MAX_PER_PAGE = 100
_KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
RANGE_NAMES = ("today", "yesterday", "this_week", "this_month", "previous_month")
SORTS = {"date": Transaction.transaction_date, "amount": Transaction.amount, "created": Transaction.created_at}
TEXT_LIMITS = {"merchant": 120, "description": 255, "notes": 2000}


def _invalid(field: str, message: str) -> ValidationFailed:
    return ValidationFailed("Some fields are invalid.", details={field: message})


def user_today(user: User) -> date:
    """'Today' in the user's own timezone, never the server's."""
    return datetime.now(ZoneInfo(user.preferences.timezone)).date()


def resolve_range(name: str, today: date) -> tuple[date, date]:
    if name == "today":
        return today, today
    if name == "yesterday":
        day = today - timedelta(days=1)
        return day, day
    if name == "this_week":  # weeks start on Monday
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    if name == "this_month":
        start = today.replace(day=1)
        return start, (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    if name == "previous_month":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    raise _invalid("range", f"Use one of: {', '.join(RANGE_NAMES)}.")


def parse_iso_date(value, field: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise _invalid(field, "Use the format YYYY-MM-DD.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _invalid(field, "That is not a real calendar date.") from None


def _clean_text(value, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid(field, "Must be text.")
    text = value.strip()
    if len(text) > TEXT_LIMITS[field]:
        raise _invalid(field, f"Use at most {TEXT_LIMITS[field]} characters.")
    return text or None


def _lookup(getter, user: User, raw_id, field: str, *, require_active: bool):
    try:
        row = getter(user, raw_id)
    except ApiError:
        raise _invalid(field, "Unknown value.") from None
    if require_active and row.is_archived:
        raise _invalid(field, "This one is archived. Pick an active one.")
    return row


def _apply_fields(user: User, txn: Transaction, data: dict, provided: set[str]) -> None:
    """Validate `provided` fields and write them onto txn. Raises ValidationFailed."""
    today = user_today(user)

    if "type" in provided:
        if data["type"] not in TRANSACTION_TYPES:
            raise _invalid("type", "Must be expense or income.")
        txn.type = data["type"]
    if "amount" in provided:
        txn.amount = parse_amount(data["amount"])
    if "transaction_date" in provided:
        if data["transaction_date"] is None:
            raise _invalid("transaction_date", "Enter a date.")
        parsed = parse_iso_date(data["transaction_date"], "transaction_date")
        if parsed > today:
            raise _invalid("transaction_date", "Future dates are not allowed.")
        if parsed < MIN_DATE:
            raise _invalid("transaction_date", f"Date must be on or after {MIN_DATE.isoformat()}.")
        txn.transaction_date = parsed

    if "account_id" in provided:
        if data["account_id"] is None:
            txn.account, txn.account_id = None, None
        else:
            changed = data["account_id"] != txn.account_id
            account = _lookup(catalog_service.get_account, user, data["account_id"], "account_id", require_active=changed)
            txn.account, txn.account_id = account, account.id
    if "category_id" in provided:
        if data["category_id"] is None:
            txn.category, txn.category_id = None, None
        else:
            changed = data["category_id"] != txn.category_id
            category = _lookup(catalog_service.get_category, user, data["category_id"], "category_id", require_active=changed)
            txn.category, txn.category_id = category, category.id

    if "currency" in provided and data["currency"]:
        txn.currency = normalize_currency(data["currency"])
    elif not txn.currency:
        txn.currency = txn.account.currency if txn.account else user.preferences.currency
    if txn.account is not None and txn.currency != txn.account.currency:
        raise _invalid("currency", f"This account uses {txn.account.currency}; amounts are never mixed across currencies.")

    if txn.category is not None and txn.category.kind != txn.type:
        raise _invalid("category_id", f"This is an {txn.category.kind} category, but the transaction is {txn.type}.")

    if "payment_method" in provided:
        if data["payment_method"] is not None and data["payment_method"] not in PAYMENT_METHODS:
            raise _invalid("payment_method", f"Use one of: {', '.join(PAYMENT_METHODS)}.")
        txn.payment_method = data["payment_method"]
    for field in TEXT_LIMITS:
        if field in provided:
            setattr(txn, field, _clean_text(data[field], field))


def find_possible_duplicates(user: User, txn: Transaction) -> list[uuid.UUID]:
    """Same type, amount, date and merchant. A warning for review, never an automatic action."""
    merchant_match = (
        Transaction.merchant.is_(None) if txn.merchant is None
        else func.lower(Transaction.merchant) == txn.merchant.lower()
    )
    stmt = (
        select(Transaction.id)
        .where(
            Transaction.user_id == user.id,
            Transaction.id != txn.id,
            Transaction.type == txn.type,
            Transaction.amount == txn.amount,
            Transaction.currency == txn.currency,
            Transaction.transaction_date == txn.transaction_date,
            merchant_match,
        )
        .limit(3)
    )
    return list(db.session.execute(stmt).scalars())


def _by_key(user: User, key: str) -> Transaction | None:
    return db.session.execute(
        select(Transaction).where(Transaction.user_id == user.id, Transaction.idempotency_key == key)
    ).scalar_one_or_none()


def create_transaction(user: User, data: dict, provided: set[str], *, idempotency_key: str | None = None, source: str = "manual"):
    """Returns (transaction, created, duplicate_ids). A retried key returns the original, unchanged."""
    if idempotency_key is not None:
        if not _KEY_PATTERN.fullmatch(idempotency_key):
            raise ApiError("Idempotency-Key must be 1-64 letters, digits, - or _.", status_code=400, code="invalid_idempotency_key")
        existing = _by_key(user, idempotency_key)
        if existing is not None:
            return existing, False, []

    for required in ("type", "amount"):
        if required not in provided:
            raise _invalid(required, "This field is required.")
    provided = set(provided)
    if "transaction_date" not in provided or data.get("transaction_date") is None:
        data = {**data, "transaction_date": user_today(user).isoformat()}  # documented default: today in user's timezone
        provided.add("transaction_date")

    txn = Transaction(user_id=user.id, source=source, idempotency_key=idempotency_key)
    _apply_fields(user, txn, data, provided)
    duplicates = find_possible_duplicates(user, txn)
    db.session.add(txn)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if idempotency_key is not None and (existing := _by_key(user, idempotency_key)) is not None:
            return existing, False, []  # a concurrent request with the same key won
        raise
    return txn, True, duplicates


def get_transaction(user: User, transaction_id: uuid.UUID) -> Transaction:
    row = db.session.execute(
        select(Transaction)
        .options(joinedload(Transaction.category), joinedload(Transaction.account))
        .where(Transaction.id == transaction_id, Transaction.user_id == user.id)
    ).scalar_one_or_none()
    if row is None:
        raise ApiError("Transaction not found.", status_code=404, code="not_found")
    return row


def update_transaction(user: User, transaction_id: uuid.UUID, data: dict, provided: set[str]):
    txn = get_transaction(user, transaction_id)
    if not provided:
        raise ApiError("Nothing to update.", status_code=400, code="empty_update")
    if "type" in provided and "category_id" not in provided and txn.category_id is not None:
        provided = provided | {"category_id"}
        data = {**data, "category_id": txn.category_id}  # re-validate the kept category against the new type
    _apply_fields(user, txn, data, provided)
    duplicates = find_possible_duplicates(user, txn)
    db.session.commit()
    return txn, duplicates


def delete_transaction(user: User, transaction_id: uuid.UUID) -> None:
    """Permanent. Only the id and type are recorded in the audit trail, never amounts or text."""
    txn = get_transaction(user, transaction_id)
    kind = txn.type
    db.session.delete(txn)
    db.session.commit()
    record_event("transaction.deleted", user.id, transaction_id=str(transaction_id), type=kind)



def _uuid_arg(args, name: str) -> uuid.UUID | None:
    raw = args.get(name)
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise _invalid(name, "Not a valid id.") from None


def _decimal_arg(args, name: str) -> Decimal | None:
    raw = args.get(name)
    if raw in (None, ""):
        return None
    try:
        return parse_amount(raw, name)
    except ValidationFailed:
        raise _invalid(name, "Enter a valid amount.") from None


def build_filters(user: User, args) -> list:
    """Translate validated query-string filters into SQL conditions (always user-scoped)."""
    conditions = [Transaction.user_id == user.id]
    today = user_today(user)

    date_from = date_to = None
    if args.get("range") and args["range"] != "custom":
        date_from, date_to = resolve_range(args["range"], today)
    else:
        if args.get("date_from"):
            date_from = parse_iso_date(args["date_from"], "date_from")
        if args.get("date_to"):
            date_to = parse_iso_date(args["date_to"], "date_to")
    if date_from and date_to and date_from > date_to:
        raise _invalid("date_from", "Start date is after the end date.")
    if date_from:
        conditions.append(Transaction.transaction_date >= date_from)
    if date_to:
        conditions.append(Transaction.transaction_date <= date_to)

    if args.get("type"):
        if args["type"] not in TRANSACTION_TYPES:
            raise _invalid("type", "Must be expense or income.")
        conditions.append(Transaction.type == args["type"])
    if args.get("payment_method"):
        if args["payment_method"] not in PAYMENT_METHODS:
            raise _invalid("payment_method", "Unknown payment method.")
        conditions.append(Transaction.payment_method == args["payment_method"])
    if args.get("source"):
        conditions.append(Transaction.source == args["source"])
    if (category_id := _uuid_arg(args, "category_id")) is not None:
        conditions.append(Transaction.category_id == category_id)
    if (account_id := _uuid_arg(args, "account_id")) is not None:
        conditions.append(Transaction.account_id == account_id)
    if (low := _decimal_arg(args, "min_amount")) is not None:
        conditions.append(Transaction.amount >= low)
    if (high := _decimal_arg(args, "max_amount")) is not None:
        conditions.append(Transaction.amount <= high)
    if args.get("currency"):
        conditions.append(Transaction.currency == normalize_currency(args["currency"]))

    if text := (args.get("q") or "").strip()[:100]:
        escaped = text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        conditions.append(
            or_(
                func.lower(Transaction.merchant).like(pattern, escape="\\"),
                func.lower(Transaction.description).like(pattern, escape="\\"),
                func.lower(Transaction.notes).like(pattern, escape="\\"),
            )
        )
    return conditions


def list_transactions(user: User, args) -> dict:
    conditions = build_filters(user, args)
    try:
        page = max(1, int(args.get("page", 1)))
        per_page = min(MAX_PER_PAGE, max(1, int(args.get("per_page", 25))))
    except ValueError:
        raise _invalid("page", "page and per_page must be whole numbers.") from None
    sort_key = args.get("sort", "date")
    if sort_key not in SORTS:
        raise _invalid("sort", f"Use one of: {', '.join(SORTS)}.")
    column = SORTS[sort_key]
    ordering = column.asc() if args.get("order") == "asc" else column.desc()

    total = db.session.execute(select(func.count()).select_from(Transaction).where(*conditions)).scalar_one()
    rows = db.session.execute(
        select(Transaction)
        .options(joinedload(Transaction.category), joinedload(Transaction.account))
        .where(*conditions)
        .order_by(ordering, Transaction.created_at.desc(), Transaction.id)
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).scalars().all()
    return {
        "items": [row.to_public_dict() for row in rows],
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": max(1, -(-total // per_page)),
    }


def summarize(user: User, args) -> list[dict]:
    """Totals per currency (never summed across currencies), computed in SQL over the same filters."""
    conditions = build_filters(user, args)
    rows = db.session.execute(
        select(Transaction.currency, Transaction.type, func.sum(Transaction.amount), func.count())
        .where(*conditions)
        .group_by(Transaction.currency, Transaction.type)
    ).all()
    by_currency: dict[str, dict] = {}
    for currency, kind, total, count in rows:
        # str() first: SQLite sums as float; PostgreSQL returns Decimal. Quantizing restores exact cents.
        entry = by_currency.setdefault(
            currency, {"currency": currency, "income": Decimal("0"), "expense": Decimal("0"), "count": 0}
        )
        entry[kind] = Decimal(str(total)).quantize(CENT)
        entry["count"] += count
    result = []
    for entry in sorted(by_currency.values(), key=lambda e: e["currency"]):
        net = entry["income"] - entry["expense"]
        result.append(
            {
                "currency": entry["currency"],
                "income": format_amount(entry["income"]),
                "expense": format_amount(entry["expense"]),
                "net": format_amount(net),
                "count": entry["count"],
            }
        )
    return result
