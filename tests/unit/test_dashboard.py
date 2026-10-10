"""Dashboard figures: every number must come from the user's stored transactions, per currency and period."""
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

DASHBOARD = "/api/v1/dashboard"


def today():
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def add(api, kind, amount, days_ago=0, **extra):
    body = {"type": kind, "amount": amount, "transaction_date": (today() - timedelta(days=days_ago)).isoformat(), **extra}
    res = api.post("/api/v1/transactions", body)
    assert res.status_code == 201, res.get_json()
    return res.get_json()["data"]["transaction"]


def fetch(api, **params):
    query = "&".join(f"{key}={value}" for key, value in params.items())
    res = api.get(f"{DASHBOARD}?{query}")
    assert res.status_code == 200, res.get_json()
    return res.get_json()["data"]


@pytest.fixture()
def alice(api):
    api.register()
    return api


def test_a_new_account_shows_no_figures_at_all(alice):
    data = fetch(alice)
    assert data["has_transactions"] is False and data["has_activity"] is False
    assert data["recent"] == [] and data["categories"] == [] and data["currencies"] == []
    assert data["summary"]["income"] == data["summary"]["expense"] == data["summary"]["balance"] == "0.00"
    assert data["summary"]["savings_rate"] is None and data["summary"]["income_change"] is None
    assert len(data["months"]) >= 6 and all(m["income"] == m["expense"] == "0.00" for m in data["months"])


def test_summary_is_calculated_from_stored_transactions(alice):
    add(alice, "income", "1000")
    add(alice, "expense", "250.50")
    data = fetch(alice)
    assert data["has_activity"] is True
    assert data["summary"]["income"] == "1000.00" and data["summary"]["expense"] == "250.50"
    assert data["summary"]["savings"] == "749.50" and data["summary"]["savings_rate"] == "75.0"
    assert data["summary"]["balance"] == "749.50"
    assert len(data["recent"]) == 2


def test_balance_counts_all_time_while_the_period_counts_only_its_own_days(alice):
    add(alice, "income", "500", days_ago=400)
    add(alice, "income", "1000")
    add(alice, "expense", "250")
    data = fetch(alice, range="this_month")
    assert data["summary"]["income"] == "1000.00"
    assert data["summary"]["balance"] == "1250.00"


def test_spending_can_exceed_income_and_savings_go_negative(alice):
    add(alice, "income", "100")
    add(alice, "expense", "400")
    summary = fetch(alice)["summary"]
    assert summary["savings"] == "-300.00" and summary["savings_rate"] == "-300.0" and summary["balance"] == "-300.00"


def test_comparison_with_the_previous_period(alice):
    start = fetch(alice)["range"]["start"]
    days_in = (today() - datetime.fromisoformat(start).date()).days + 1
    add(alice, "expense", "100")
    add(alice, "expense", "50", days_ago=days_in)  # lands in the equally long period before this one
    summary = fetch(alice)["summary"]
    assert summary["expense_change"] == "100.0"  # 100 now vs 50 before
    assert summary["income_change"] is None  # no earlier income to compare with


def test_monthly_series_adds_up_to_the_stored_data(alice):
    add(alice, "expense", "40")
    add(alice, "expense", "60", days_ago=70)
    add(alice, "income", "900", days_ago=70)
    data = fetch(alice, range="last_6_months")
    assert sum(Decimal(m["expense"]) for m in data["months"]) == Decimal("100.00")
    assert sum(Decimal(m["income"]) for m in data["months"]) == Decimal("900.00")
    assert data["months"] == sorted(data["months"], key=lambda m: m["month"])
    assert data["months"][-1]["month"] == today().strftime("%Y-%m")


def test_trend_is_daily_for_short_ranges_and_weekly_for_long_ones(alice):
    add(alice, "expense", "30")
    add(alice, "expense", "70", days_ago=100)
    short = fetch(alice, range="this_month")["trend"]
    assert short["granularity"] == "day" and sum(Decimal(p["amount"]) for p in short["points"]) == Decimal("30.00")
    long = fetch(alice, range="last_6_months")["trend"]
    assert long["granularity"] == "week" and sum(Decimal(p["amount"]) for p in long["points"]) == Decimal("100.00")
    assert all(datetime.fromisoformat(p["date"]).weekday() == 0 for p in long["points"])  # weeks start on Monday


def test_categories_are_ranked_with_the_tail_grouped_as_other(alice):
    for index in range(7):
        category = alice.post("/api/v1/categories", {"name": f"Group {index}", "kind": "expense"}).get_json()["data"]["category"]
        add(alice, "expense", str(100 - index * 10), category_id=category["id"])
    add(alice, "expense", "5")  # no category
    categories = fetch(alice)["categories"]
    assert [c["name"] for c in categories][:5] == [f"Group {i}" for i in range(5)]
    assert categories[-1]["name"] == "Other" and len(categories) == 6
    assert sum(Decimal(c["amount"]) for c in categories) == Decimal("495.00")
    assert abs(sum(Decimal(c["share"]) for c in categories) - 100) < Decimal("0.5")


def test_only_expenses_in_the_period_feed_the_category_chart(alice):
    add(alice, "income", "1000")
    add(alice, "expense", "20", days_ago=400)
    assert fetch(alice)["categories"] == []


def test_currencies_are_never_mixed(alice):
    add(alice, "expense", "100")
    add(alice, "expense", "7", currency="USD")
    inr, usd = fetch(alice), fetch(alice, currency="USD")
    assert inr["currencies"] == ["INR", "USD"] and inr["currency"] == "INR"
    assert inr["summary"]["expense"] == "100.00" and usd["summary"]["expense"] == "7.00"
    assert [t["currency"] for t in usd["recent"]] == ["USD"]
    assert fetch(alice, currency="EUR")["currency"] == "INR"  # unknown currency falls back to the default


def test_unknown_ranges_are_rejected_and_data_stays_private(alice, make_api):
    assert alice.get(f"{DASHBOARD}?range=forever").status_code == 422
    add(alice, "expense", "10")
    other = make_api()
    other.register(email="bob@example.com", name="Bob")
    assert fetch(other)["has_transactions"] is False


def test_dashboard_page_has_the_filters_and_chart_hosts(alice):
    html = alice.get("/dashboard").get_data(as_text=True)
    for marker in ('id="dashboard-range"', 'id="chart-bars"', 'id="chart-donut"', 'id="chart-trend"', 'id="dashboard-stats"'):
        assert marker in html, marker
