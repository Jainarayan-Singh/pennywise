from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import AuditEvent, Category, Transaction, User
from app.services.transaction_service import resolve_range

TX = "/api/v1/transactions"
CAT = "/api/v1/categories"
ACC = "/api/v1/accounts"


@pytest.fixture()
def alice(api):
    api.register()
    return api


@pytest.fixture()
def bob(make_api):
    browser = make_api()
    browser.register(email="bob@example.com", name="Bob")
    return browser


def categories(api, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return api.get(f"{CAT}?{query}").get_json()["data"]["categories"]


def category_id(api, name, kind="expense"):
    return next(c["id"] for c in categories(api, include_archived="true") if c["name"] == name and c["kind"] == kind)


def make_account(api, name="HDFC", account_type="bank", **extra):
    res = api.post(ACC, {"name": name, "account_type": account_type, **extra})
    assert res.status_code == 201, res.get_json()
    return res.get_json()["data"]["account"]


def make_txn(api, amount="250.00", **fields):
    payload = {"type": "expense", "amount": amount, **fields}
    return api.post(TX, payload)


def txn_data(res):
    return res.get_json()["data"]["transaction"]


# --- categories ---------------------------------------------------------------------------


def test_default_categories_seeded_once_per_user(alice, bob):
    names = [(c["kind"], c["name"]) for c in categories(alice)]
    assert len([n for n in names if n[0] == "expense"]) == 12 and len([n for n in names if n[0] == "income"]) == 5
    assert len(categories(alice)) == 17  # repeated reads don't duplicate
    assert len(categories(bob)) == 17
    assert db.session.query(Category).count() == 34


def test_custom_category_uniqueness_is_case_insensitive_per_kind(alice):
    assert alice.post(CAT, {"name": "Pets", "kind": "expense"}).status_code == 201
    dup = alice.post(CAT, {"name": "  pets ", "kind": "expense"})
    assert dup.status_code == 409 and dup.get_json()["error"]["code"] == "duplicate_name"
    assert alice.post(CAT, {"name": "Pets", "kind": "income"}).status_code == 201  # other kind is fine
    assert alice.post(CAT, {"name": "x", "kind": "transfer"}).status_code == 422
    assert alice.post(CAT, {"name": "   ", "kind": "expense"}).status_code == 422


def test_archive_hides_category_but_keeps_history(alice):
    cat = category_id(alice, "Groceries")
    txn_id = txn_data(make_txn(alice, category_id=cat))["id"]
    assert alice.request("PATCH", f"{CAT}/{cat}", {"is_archived": True}).status_code == 200
    assert "Groceries" not in [c["name"] for c in categories(alice)]
    assert "Groceries" in [c["name"] for c in categories(alice, include_archived="true")]
    assert alice.get(f"{TX}/{txn_id}").get_json()["data"]["transaction"]["category"]["name"] == "Groceries"
    # a new transaction can't use it, but the old one can still be edited while keeping it
    assert make_txn(alice, category_id=cat).status_code == 422
    assert alice.request("PATCH", f"{TX}/{txn_id}", {"notes": "still fine"}).status_code == 200


def test_category_rename_and_empty_patch(alice):
    cat = category_id(alice, "Other")
    assert alice.request("PATCH", f"{CAT}/{cat}", {"name": "Misc"}).get_json()["data"]["category"]["name"] == "Misc"
    assert alice.request("PATCH", f"{CAT}/{cat}", {}).status_code == 400


# --- accounts -----------------------------------------------------------------------------


def test_accounts_default_currency_and_validation(alice):
    acc = make_account(alice)
    assert acc["currency"] == "INR"
    assert make_account(alice, "Cash wallet", "cash", currency="usd")["currency"] == "USD"
    assert alice.post(ACC, {"name": "HDFC", "account_type": "bank"}).status_code == 409
    assert alice.post(ACC, {"name": "X", "account_type": "crypto"}).status_code == 422
    assert alice.post(ACC, {"name": "X", "account_type": "bank", "currency": "RUPEES"}).status_code == 422
    # currency/type are immutable
    assert alice.request("PATCH", f"{ACC}/{acc['id']}", {"currency": "USD"}).status_code == 422


# --- amounts ------------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [("250", "250.00"), ("250.5", "250.50"), (250, "250.00"), (0.1, "0.10"), ("0.01", "0.01"), ("999999999999.99", "999999999999.99")])
def test_valid_amounts_are_stored_exactly(alice, raw, expected):
    assert txn_data(make_txn(alice, raw))["amount"] == expected


@pytest.mark.parametrize("raw", ["-5", "0", "0.00", "1,250", "1e3", "2.555", "abc", "", None, True, [], "₹250", "1000000000000"])
def test_malformed_or_suspicious_amounts_are_rejected_not_guessed(alice, raw):
    res = make_txn(alice, raw)
    assert res.status_code == 422 and "amount" in res.get_json()["error"]["details"]
    assert db.session.query(Transaction).count() == 0


def test_missing_amount_is_not_treated_as_zero(alice):
    res = alice.post(TX, {"type": "expense"})
    assert res.status_code == 422 and "amount" in res.get_json()["error"]["details"]


def test_summation_is_exact_to_the_cent(alice):
    for amount in ("0.10", "0.20", "0.30", "19.99", "0.01"):
        make_txn(alice, amount)
    totals = alice.get(f"{TX}/summary").get_json()["data"]["totals"]
    assert totals == [{"currency": "INR", "income": "0.00", "expense": "20.60", "net": "-20.60", "count": 5}]


# --- dates --------------------------------------------------------------------------------


def test_date_defaults_to_today_in_the_users_timezone(alice):
    user = db.session.query(User).one()
    user.preferences.timezone = "Pacific/Kiritimati"  # UTC+14: often a different calendar day than UTC
    db.session.commit()
    expected = datetime.now(ZoneInfo("Pacific/Kiritimati")).date().isoformat()
    assert txn_data(make_txn(alice))["transaction_date"] == expected


@pytest.mark.parametrize("raw", ["07/10/2026", "2026-02-30", "2026-13-01", "yesterday", "1999-12-31", 20261007])
def test_ambiguous_or_invalid_dates_are_rejected(alice, raw):
    assert make_txn(alice, transaction_date=raw).status_code == 422


def test_future_dates_rejected_and_today_accepted(alice):
    tomorrow = (datetime.now(ZoneInfo("Asia/Kolkata")).date() + timedelta(days=2)).isoformat()
    assert make_txn(alice, transaction_date=tomorrow).status_code == 422
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    assert make_txn(alice, transaction_date=today).status_code == 201


def test_resolve_range_rules():
    wed = date(2026, 10, 7)
    assert resolve_range("today", wed) == (wed, wed)
    assert resolve_range("yesterday", wed) == (date(2026, 10, 6), date(2026, 10, 6))
    assert resolve_range("this_week", wed) == (date(2026, 10, 5), date(2026, 10, 11))  # Monday-Sunday
    assert resolve_range("this_month", wed) == (date(2026, 10, 1), date(2026, 10, 31))
    assert resolve_range("previous_month", wed) == (date(2026, 9, 1), date(2026, 9, 30))
    assert resolve_range("previous_month", date(2026, 1, 15)) == (date(2025, 12, 1), date(2025, 12, 31))
    assert resolve_range("this_month", date(2024, 2, 10)) == (date(2024, 2, 1), date(2024, 2, 29))  # leap year
    assert resolve_range("this_month", date(2026, 12, 31))[1] == date(2026, 12, 31)


# --- relationships & currency -------------------------------------------------------------


def test_category_kind_must_match_transaction_type(alice):
    salary = category_id(alice, "Salary", "income")
    res = make_txn(alice, category_id=salary)
    assert res.status_code == 422 and "category_id" in res.get_json()["error"]["details"]
    assert alice.post(TX, {"type": "income", "amount": "5000", "category_id": salary}).status_code == 201


def test_currency_comes_from_account_and_mixing_is_refused(alice):
    usd = make_account(alice, "Travel card", "card", currency="USD")
    assert txn_data(make_txn(alice, account_id=usd["id"]))["currency"] == "USD"
    assert make_txn(alice, account_id=usd["id"], currency="INR").status_code == 422
    assert txn_data(make_txn(alice))["currency"] == "INR"  # user's default when there is no account


def test_summary_never_adds_different_currencies(alice):
    usd = make_account(alice, "Travel card", "card", currency="USD")
    make_txn(alice, "100")
    make_txn(alice, "7.50", account_id=usd["id"])
    totals = {t["currency"]: t["expense"] for t in alice.get(f"{TX}/summary").get_json()["data"]["totals"]}
    assert totals == {"INR": "100.00", "USD": "7.50"}


def test_payment_method_and_text_validation(alice):
    assert make_txn(alice, payment_method="upi").status_code == 201
    assert make_txn(alice, payment_method="barter").status_code == 422
    assert make_txn(alice, merchant="x" * 121).status_code == 422
    assert txn_data(make_txn(alice, merchant="  Cafe  ", notes="   "))["notes"] is None
    assert make_txn(alice, source="ai").status_code == 422  # clients can't set the source


# --- idempotency & duplicates -------------------------------------------------------------


def test_idempotency_key_prevents_double_saves(alice):
    def post():
        return alice.client.post(TX, json={"type": "expense", "amount": "99"}, headers={"X-CSRF-Token": alice.csrf, "Idempotency-Key": "form-abc_123"})

    alice.refresh_csrf()
    first, second = post(), post()
    assert first.status_code == 201 and second.status_code == 200
    assert second.get_json()["idempotent_replay"] is True
    assert txn_data(first)["id"] == txn_data(second)["id"]
    assert db.session.query(Transaction).count() == 1


def test_idempotency_keys_are_scoped_per_user_and_validated(alice, bob):
    for browser in (alice, bob):
        browser.refresh_csrf()
        res = browser.client.post(TX, json={"type": "expense", "amount": "5"}, headers={"X-CSRF-Token": browser.csrf, "Idempotency-Key": "same-key"})
        assert res.status_code == 201
    assert db.session.query(Transaction).count() == 2
    bad = alice.client.post(TX, json={"type": "expense", "amount": "5"}, headers={"X-CSRF-Token": alice.csrf, "Idempotency-Key": "bad key!"})
    assert bad.status_code == 400


def test_possible_duplicates_are_warned_not_blocked(alice):
    first = make_txn(alice, "250", merchant="Cafe", transaction_date="2026-10-01")
    second = make_txn(alice, "250", merchant="cafe", transaction_date="2026-10-01")
    assert second.status_code == 201
    warning = second.get_json()["warnings"][0]
    assert warning["code"] == "possible_duplicate" and warning["transaction_ids"] == [txn_data(first)["id"]]
    assert make_txn(alice, "250", merchant="Cafe", transaction_date="2026-10-02").get_json()["warnings"] == []
    assert db.session.query(Transaction).count() == 3


# --- update / delete ----------------------------------------------------------------------


def test_partial_update_and_clearing_fields(alice):
    cat = category_id(alice, "Groceries")
    txn = txn_data(make_txn(alice, "100", category_id=cat, merchant="Mart"))
    res = alice.request("PATCH", f"{TX}/{txn['id']}", {"amount": "120.5", "category_id": None})
    data = txn_data(res)
    assert data["amount"] == "120.50" and data["category"] is None and data["merchant"] == "Mart"
    assert alice.request("PATCH", f"{TX}/{txn['id']}", {}).status_code == 400
    assert alice.request("PATCH", f"{TX}/{txn['id']}", {"amount": "-1"}).status_code == 422
    assert alice.request("PATCH", f"{TX}/{txn['id']}", {"user_id": "x"}).status_code == 422
    assert alice.get(f"{TX}/{txn['id']}").get_json()["data"]["transaction"]["amount"] == "120.50"


def test_changing_type_revalidates_the_kept_category(alice):
    cat = category_id(alice, "Groceries")
    txn = txn_data(make_txn(alice, category_id=cat))
    res = alice.request("PATCH", f"{TX}/{txn['id']}", {"type": "income"})
    assert res.status_code == 422
    assert alice.request("PATCH", f"{TX}/{txn['id']}", {"type": "income", "category_id": None}).status_code == 200


def test_delete_removes_and_audits_without_amounts(alice):
    txn = txn_data(make_txn(alice, "1234.56", description="secret lunch"))
    assert alice.delete(f"{TX}/{txn['id']}").status_code == 200
    assert alice.get(f"{TX}/{txn['id']}").status_code == 404
    assert alice.delete(f"{TX}/{txn['id']}").status_code == 404
    event = db.session.query(AuditEvent).filter_by(event_type="transaction.deleted").one()
    assert "1234" not in str(event.details) and "secret" not in str(event.details)


# --- isolation ----------------------------------------------------------------------------


def test_users_cannot_see_or_touch_each_others_data(alice, bob):
    a_txn = txn_data(make_txn(alice, "500", description="alice only"))
    a_cat = category_id(alice, "Groceries")
    a_acc = make_account(alice)
    categories(bob)  # seed bob's defaults

    assert bob.get(f"{TX}/{a_txn['id']}").status_code == 404
    assert bob.request("PATCH", f"{TX}/{a_txn['id']}", {"amount": "1"}).status_code == 404
    assert bob.delete(f"{TX}/{a_txn['id']}").status_code == 404
    assert bob.get(TX).get_json()["data"]["total"] == 0
    assert bob.get(f"{TX}/summary").get_json()["data"]["totals"] == []
    assert bob.request("PATCH", f"{CAT}/{a_cat}", {"is_archived": True}).status_code == 404
    assert bob.request("PATCH", f"{ACC}/{a_acc['id']}", {"name": "hacked"}).status_code == 404
    # using someone else's ids in a body is rejected like an unknown id
    assert make_txn(bob, category_id=a_cat).status_code == 422
    assert make_txn(bob, account_id=a_acc["id"]).status_code == 422
    assert "alice only" not in str(bob.get(f"{TX}?q=alice").get_json())
    assert bob.get(ACC).get_json()["data"]["accounts"] == []
    assert alice.get(f"{TX}/{a_txn['id']}").get_json()["data"]["transaction"]["amount"] == "500.00"


def test_endpoints_require_authentication_and_csrf(alice, make_api):
    anon = make_api()
    for method, url in (("GET", TX), ("GET", f"{TX}/summary"), ("GET", CAT), ("GET", ACC)):
        assert anon.request(method, url).status_code == 401, url
    assert anon.post(TX, {"type": "expense", "amount": "5"}).status_code == 401
    assert alice.post(TX, {"type": "expense", "amount": "5"}, csrf=False).status_code == 403


# --- pages --------------------------------------------------------------------------------


def test_transactions_page_gets_its_choices_from_the_server(alice):
    page = alice.get("/transactions").get_data(as_text=True)
    assert 'data-currency="INR"' in page and "UPI" in page and "This month" in page
    assert "Bank" in alice.get("/manage").get_data(as_text=True)


# --- listing ------------------------------------------------------------------------------


@pytest.fixture()
def sample(alice):
    groceries = category_id(alice, "Groceries")
    food = category_id(alice, "Food & Dining")
    acc = make_account(alice)
    rows = [
        ("100", "2026-10-01", {"merchant": "Big Bazaar", "category_id": groceries}),
        ("250", "2026-10-02", {"merchant": "Cafe 100%", "category_id": food, "payment_method": "upi"}),
        ("75.5", "2026-10-03", {"merchant": "Auto", "account_id": acc["id"]}),
        ("1200", "2026-09-15", {"description": "Petrol_fill"}),
        ("30", "2026-10-04", {"merchant": "Tea stall"}),
    ]
    for amount, day, extra in rows:
        assert make_txn(alice, amount, transaction_date=day, **extra).status_code == 201
    alice.post(TX, {"type": "income", "amount": "5000", "transaction_date": "2026-10-01"})
    return {"groceries": groceries, "food": food, "acc": acc}


def listing(api, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return api.get(f"{TX}?{query}").get_json()["data"]


def test_pagination_sorting_and_defaults(alice, sample):
    page1 = listing(alice, per_page=2)
    assert page1["total"] == 6 and page1["pages"] == 3 and len(page1["items"]) == 2
    assert [t["transaction_date"] for t in page1["items"]] == ["2026-10-04", "2026-10-03"]  # newest first
    assert listing(alice, per_page=2, page=3)["items"][-1]["transaction_date"] == "2026-09-15"
    assert [t["amount"] for t in listing(alice, sort="amount", order="asc", per_page=3)["items"]] == ["30.00", "75.50", "100.00"]
    assert listing(alice, per_page=1000)["per_page"] == 100  # capped


def test_filters(alice, sample):
    assert listing(alice, type="income")["total"] == 1
    assert listing(alice, category_id=sample["groceries"])["total"] == 1
    assert listing(alice, account_id=sample["acc"]["id"])["total"] == 1
    assert listing(alice, min_amount=100, max_amount=250)["total"] == 2
    assert listing(alice, payment_method="upi")["total"] == 1
    assert listing(alice, date_from="2026-10-02", date_to="2026-10-03")["total"] == 2
    assert listing(alice, date_to="2026-09-30")["total"] == 1
    assert listing(alice, currency="usd")["total"] == 0


def test_text_search_treats_wildcards_literally_and_resists_injection(alice, sample):
    assert listing(alice, q="cafe")["total"] == 1
    assert listing(alice, q="100%25")["total"] == 1  # "100%" matches only the literal text
    assert listing(alice, q="_")["total"] == 1       # only "Petrol_fill", not every row
    assert listing(alice, q="%27%20OR%201%3D1%20--")["total"] == 0
    assert db.session.query(Transaction).count() == 6


@pytest.mark.parametrize("params", ["category_id=nope", "date_from=2026/10/01", "sort=password", "type=transfer",
                                    "page=abc", "min_amount=-1", "range=forever", "date_from=2026-10-05&date_to=2026-10-01"])
def test_invalid_query_parameters_are_rejected(alice, sample, params):
    assert alice.get(f"{TX}?{params}").status_code == 422


def test_summary_follows_filters(alice, sample):
    totals = alice.get(f"{TX}/summary?date_from=2026-10-01&date_to=2026-10-31").get_json()["data"]["totals"]
    assert totals == [{"currency": "INR", "income": "5000.00", "expense": "455.50", "net": "4544.50", "count": 5}]


# --- database-level guarantees ------------------------------------------------------------


def test_database_rejects_non_positive_amounts_and_bad_enums(alice):
    user = db.session.query(User).one()
    for kwargs in ({"amount": 0}, {"amount": -5}, {"type": "transfer"}, {"payment_method": "barter"}, {"source": "magic"}):
        base = dict(user_id=user.id, type="expense", amount=10, currency="INR", transaction_date=date(2026, 10, 1))
        db.session.add(Transaction(**{**base, **kwargs}))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_deleting_a_user_removes_their_financial_rows(alice):
    make_txn(alice, "10")
    categories(alice)
    user = db.session.query(User).one()
    db.session.delete(user)
    db.session.commit()
    if db.engine.dialect.name == "postgresql":  # SQLite doesn't enforce FK cascades by default
        assert db.session.query(Transaction).count() == 0 and db.session.query(Category).count() == 0


# --- archived views -----------------------------------------------------------------------------


def test_archived_only_lists_just_the_archived_items(alice):
    groceries, fuel = category_id(alice, "Groceries"), category_id(alice, "Fuel")
    acc = make_account(alice, "Old card", "card")
    make_account(alice, "Current", "bank")
    for path in (f"{CAT}/{groceries}", f"{CAT}/{fuel}", f"{ACC}/{acc['id']}"):
        assert alice.request("PATCH", path, {"is_archived": True}).status_code == 200

    only = alice.get(f"{CAT}?archived=only").get_json()["data"]["categories"]
    assert sorted(c["name"] for c in only) == ["Fuel", "Groceries"] and all(c["is_archived"] for c in only)
    active = alice.get(CAT).get_json()["data"]["categories"]
    assert len(active) == 15 and not any(c["is_archived"] for c in active)
    assert len(alice.get(f"{CAT}?include_archived=true").get_json()["data"]["categories"]) == 17

    archived_accounts = alice.get(f"{ACC}?archived=only").get_json()["data"]["accounts"]
    assert [a["name"] for a in archived_accounts] == ["Old card"]
    assert [a["name"] for a in alice.get(ACC).get_json()["data"]["accounts"]] == ["Current"]
    assert len(alice.get(f"{ACC}?include_archived=true").get_json()["data"]["accounts"]) == 2


def test_restoring_moves_an_item_back_out_of_the_archived_view(alice):
    groceries = category_id(alice, "Groceries")
    alice.request("PATCH", f"{CAT}/{groceries}", {"is_archived": True})
    assert len(alice.get(f"{CAT}?archived=only").get_json()["data"]["categories"]) == 1
    alice.request("PATCH", f"{CAT}/{groceries}", {"is_archived": False})
    assert alice.get(f"{CAT}?archived=only").get_json()["data"]["categories"] == []
    assert "Groceries" in [c["name"] for c in alice.get(CAT).get_json()["data"]["categories"]]


def test_archived_view_is_scoped_to_the_signed_in_user(alice, bob):
    alice.request("PATCH", f"{CAT}/{category_id(alice, 'Groceries')}", {"is_archived": True})
    assert bob.get(f"{CAT}?archived=only").get_json()["data"]["categories"] == []
