"""Read-only figures for the dashboard, computed from the user's own recorded transactions.

Everything is for one currency at a time (amounts in different currencies are never added together) and one
date range chosen by the user. Amounts leave this module as exact decimal strings.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import Category, Transaction, User
from app.services import transaction_service
from app.services.money import CENT, format_amount
from app.utils.errors import ValidationFailed

RANGES = {
    "this_month": "This month",
    "previous_month": "Last month",
    "last_3_months": "Last 3 months",
    "last_6_months": "Last 6 months",
    "this_year": "This year",
    "last_12_months": "Last 12 months",
}
DEFAULT_RANGE = "this_month"
MIN_MONTHS_SHOWN = 6  # the month-by-month chart always has some history to compare against
DAILY_TREND_MAX_DAYS = 62  # longer ranges are summed per week so the chart stays readable
TOP_CATEGORIES = 5
RECENT_TRANSACTIONS = 6
ZERO = Decimal("0.00")


def _months_back(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 - months
    return date(index // 12, index % 12 + 1, 1)


def resolve_range(key: str, today: date) -> tuple[date, date]:
    if key == "this_month":
        return today.replace(day=1), today
    if key == "previous_month":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if key == "last_3_months":
        return _months_back(today, 2), today
    if key == "last_6_months":
        return _months_back(today, 5), today
    if key == "last_12_months":
        return _months_back(today, 11), today
    if key == "this_year":
        return date(today.year, 1, 1), today
    raise ValidationFailed("Some fields are invalid.", details={"range": f"Use one of: {', '.join(RANGES)}."})


def _currencies(user: User) -> dict[str, int]:
    rows = db.session.execute(
        select(Transaction.currency, func.count()).where(Transaction.user_id == user.id).group_by(Transaction.currency)
    ).all()
    return {currency: count for currency, count in rows}


def _pick_currency(user: User, requested: str | None, counts: dict[str, int]) -> str:
    if requested and requested.upper() in counts:
        return requested.upper()
    preferred = user.preferences.currency
    if preferred in counts or not counts:
        return preferred
    return max(counts, key=counts.get)


def _daily_sums(user: User, currency: str, start: date, end: date) -> dict[tuple[date, str], Decimal]:
    rows = db.session.execute(
        select(Transaction.transaction_date, Transaction.type, func.sum(Transaction.amount))
        .where(
            Transaction.user_id == user.id,
            Transaction.currency == currency,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        )
        .group_by(Transaction.transaction_date, Transaction.type)
    ).all()
    return {(day, kind): Decimal(str(total)).quantize(CENT) for day, kind, total in rows}


def _total(sums: dict, kind: str, start: date, end: date) -> Decimal:
    return sum((v for (day, k), v in sums.items() if k == kind and start <= day <= end), ZERO)


def _percent_change(current: Decimal, previous: Decimal) -> str | None:
    """How much `current` differs from `previous`, in percent; None when there is nothing to compare with."""
    if previous <= 0:
        return None
    return format(((current - previous) / previous * 100).quantize(Decimal("0.1")), "f")


def _balance(user: User, currency: str) -> Decimal:
    rows = db.session.execute(
        select(Transaction.type, func.sum(Transaction.amount))
        .where(Transaction.user_id == user.id, Transaction.currency == currency)
        .group_by(Transaction.type)
    ).all()
    totals = {kind: Decimal(str(total)) for kind, total in rows}
    return (totals.get("income", ZERO) - totals.get("expense", ZERO)).quantize(CENT)


def _months(sums: dict, start: date, end: date) -> list[dict]:
    first = min(start.replace(day=1), _months_back(end, MIN_MONTHS_SHOWN - 1))
    months, cursor = [], first
    while cursor <= end:
        following = _months_back(cursor, -1)
        last_day = following - timedelta(days=1)
        months.append(
            {
                "month": cursor.strftime("%Y-%m"),
                "income": format_amount(_total(sums, "income", cursor, last_day)),
                "expense": format_amount(_total(sums, "expense", cursor, last_day)),
            }
        )
        cursor = following
    return months


def _trend(sums: dict, start: date, end: date) -> dict:
    spent: dict[date, Decimal] = defaultdict(lambda: ZERO)
    for (day, kind), amount in sums.items():
        if kind == "expense" and start <= day <= end:
            spent[day] += amount
    weekly = (end - start).days + 1 > DAILY_TREND_MAX_DAYS
    buckets: dict[date, Decimal] = defaultdict(lambda: ZERO)
    cursor = start
    while cursor <= end:
        key = cursor - timedelta(days=cursor.weekday()) if weekly else cursor
        buckets[key] += spent.get(cursor, ZERO)
        cursor += timedelta(days=1)
    return {
        "granularity": "week" if weekly else "day",
        "points": [{"date": day.isoformat(), "amount": format_amount(amount)} for day, amount in sorted(buckets.items())],
    }


def _spending_by_category(user: User, currency: str, start: date, end: date) -> list[dict]:
    rows = db.session.execute(
        select(Category.name, func.sum(Transaction.amount))
        .select_from(Transaction)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .where(
            Transaction.user_id == user.id,
            Transaction.type == "expense",
            Transaction.currency == currency,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        )
        .group_by(Category.name)
    ).all()
    amounts = {(name or "Uncategorised"): Decimal(str(total)).quantize(CENT) for name, total in rows}
    grand_total = sum(amounts.values(), ZERO)
    ranked = sorted(amounts.items(), key=lambda item: item[1], reverse=True)
    shown, rest = ranked[:TOP_CATEGORIES], ranked[TOP_CATEGORIES:]
    if rest:
        shown.append(("Other", sum((amount for _, amount in rest), ZERO)))
    return [
        {"name": name, "amount": format_amount(amount), "share": format((amount / grand_total * 100).quantize(Decimal("0.1")), "f")}
        for name, amount in shown
    ]


def _recent(user: User, currency: str) -> list[dict]:
    rows = db.session.execute(
        select(Transaction)
        .options(joinedload(Transaction.category), joinedload(Transaction.account))
        .where(Transaction.user_id == user.id, Transaction.currency == currency)
        .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
        .limit(RECENT_TRANSACTIONS)
    ).scalars().all()
    return [row.to_public_dict() for row in rows]


def build_dashboard(user: User, range_key: str | None = None, currency: str | None = None) -> dict:
    range_key = range_key or DEFAULT_RANGE
    today = transaction_service.user_today(user)
    start, end = resolve_range(range_key, today)
    counts = _currencies(user)
    currency = _pick_currency(user, currency, counts)

    length = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=length - 1)
    months_start = min(start.replace(day=1), _months_back(end, MIN_MONTHS_SHOWN - 1))
    sums = _daily_sums(user, currency, min(months_start, previous_start), end)

    income, expense = _total(sums, "income", start, end), _total(sums, "expense", start, end)
    savings = income - expense
    summary = {
        "income": format_amount(income),
        "expense": format_amount(expense),
        "savings": format_amount(savings),
        "savings_rate": format((savings / income * 100).quantize(Decimal("0.1")), "f") if income > 0 else None,
        "balance": format_amount(_balance(user, currency)),
        "income_change": _percent_change(income, _total(sums, "income", previous_start, previous_end)),
        "expense_change": _percent_change(expense, _total(sums, "expense", previous_start, previous_end)),
    }
    return {
        "currency": currency,
        "currencies": sorted(counts),
        "range": {"key": range_key, "label": RANGES[range_key], "start": start.isoformat(), "end": end.isoformat()},
        "ranges": [{"key": key, "label": label} for key, label in RANGES.items()],
        "summary": summary,
        "months": _months(sums, start, end),
        "trend": _trend(sums, start, end),
        "categories": _spending_by_category(user, currency, start, end),
        "recent": _recent(user, currency),
        "has_transactions": bool(counts),
        "has_activity": income > 0 or expense > 0,
    }
