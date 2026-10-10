from flask import Blueprint, current_app, render_template

from app.models.finance import ACCOUNT_TYPES, PAYMENT_METHODS
from app.security.session import get_current_user, page_login_required
from app.services.transaction_service import MIN_DATE, RANGE_NAMES, user_today

finance_pages_bp = Blueprint("finance_pages", __name__)

_LABELS = {
    "this_week": "This week", "this_month": "This month", "previous_month": "Previous month",
    "today": "Today", "yesterday": "Yesterday", "upi": "UPI", "bank_transfer": "Bank transfer",
}


def label(value: str) -> str:
    return _LABELS.get(value, value.replace("_", " ").capitalize())


def _locale() -> str:
    return current_app.extensions["settings"].finance.default_number_format


@finance_pages_bp.get("/dashboard")
@page_login_required
def dashboard_page():
    user = get_current_user()
    return render_template("finance/dashboard.html", currency=user.preferences.currency, locale=_locale())


@finance_pages_bp.get("/transactions")
@page_login_required
def transactions_page():
    user = get_current_user()
    return render_template(
        "finance/transactions.html",
        today=user_today(user).isoformat(),
        min_date=MIN_DATE.isoformat(),
        currency=user.preferences.currency,
        locale=_locale(),
        payment_methods=PAYMENT_METHODS,
        range_names=RANGE_NAMES,
        label=label,
    )


@finance_pages_bp.get("/manage")
@page_login_required
def manage_page():
    user = get_current_user()
    return render_template(
        "finance/manage.html", currency=user.preferences.currency, account_types=ACCOUNT_TYPES, label=label
    )
