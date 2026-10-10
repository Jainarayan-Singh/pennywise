from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.integrations.ai.base import AIInvalidResponse
from app.services import expense_intent as intent
from app.utils.errors import ValidationFailed

TODAY = date(2026, 10, 8)  # a Thursday


@pytest.mark.parametrize(
    "text,expected",
    [
        ("250", "250.00"), ("250 rupees", "250.00"), ("Rs 250", "250.00"), ("rs. 250", "250.00"), ("₹250", "250.00"),
        ("250 rs", "250.00"), ("2.5k", "2500.00"), ("2.5 K", "2500.00"), ("1 lakh", "100000.00"),
        ("1.5 lakh", "150000.00"), ("2 crore", "20000000.00"), ("1,25,000", "125000.00"), ("1,250", "1250.00"),
        ("12.50", "12.50"), ("350 rupaye", "350.00"), ("$40", "40.00"), ("5 thousand", "5000.00"),
    ],
)
def test_spoken_amounts_resolve_exactly(text, expected):
    assert intent.parse_spoken_amount(text) == Decimal(expected)


@pytest.mark.parametrize(
    "text", ["", None, "abc", "five hundred", "12.345", "0", "-5", "1,2,3", "250 apples", "1e3", "99999999999999 lakh", "2.5.5"]
)
def test_malformed_or_suspicious_amounts_are_not_guessed(text):
    assert intent.parse_spoken_amount(text) is None


@pytest.mark.parametrize(
    "text,code",
    [("₹250", "INR"), ("250 rupees", "INR"), ("Rs 5", "INR"), ("40 dollars", "USD"), ("$5", "USD"), ("€9", "EUR"), ("hours", None), ("usd", "USD"), ("gbp", "GBP")],
)
def test_currency_detection_needs_a_standalone_word(text, code):
    assert intent.detect_currency(text) == code


@pytest.mark.parametrize(
    "phrase,status,expected",
    [
        ("today", "resolved", date(2026, 10, 8)),
        ("aaj", "resolved", date(2026, 10, 8)),
        ("yesterday", "resolved", date(2026, 10, 7)),
        ("kal", "resolved", date(2026, 10, 7)),
        ("day before yesterday", "resolved", date(2026, 10, 6)),
        ("3 days ago", "resolved", date(2026, 10, 5)),
        ("a week ago", "resolved", date(2026, 10, 1)),
        ("two weeks ago", "resolved", date(2026, 9, 24)),
        ("last Friday", "resolved", date(2026, 10, 2)),
        ("Monday", "resolved", date(2026, 10, 5)),
        ("last Thursday", "resolved", date(2026, 10, 1)),
        ("Thursday", "ambiguous", None),
        ("on the 5th", "resolved", date(2026, 10, 5)),
        ("the 10th", "resolved", date(2026, 9, 10)),
        ("5", "resolved", date(2026, 10, 5)),
        ("second of October", "resolved", date(2026, 10, 2)),
        ("2nd October", "resolved", date(2026, 10, 2)),
        ("October 2", "resolved", date(2026, 10, 2)),
        ("15 Dec", "resolved", date(2025, 12, 15)),
        ("15 Dec 2024", "resolved", date(2024, 12, 15)),
        ("2026-10-03", "resolved", date(2026, 10, 3)),
        ("5/10/2026", "resolved", date(2026, 10, 5)),
        ("last month", "ambiguous", None),
        ("previous month", "ambiguous", None),
        ("31st", "ambiguous", None),
        ("30 Feb", "ambiguous", None),
        ("2026-10-09", "future", None),
        ("15 Oct 2026", "future", None),
        ("whenever", "unparsed", None),
        ("", "unparsed", None),
    ],
)
def test_date_phrases_resolve_in_the_users_calendar(phrase, status, expected):
    result = intent.resolve_date_phrase(phrase, TODAY)
    assert (result.status, result.value) == (status, expected)


def test_numeric_dates_follow_the_users_date_order():
    assert intent.resolve_date_phrase("3/4/2026", TODAY, day_first=True).value == date(2026, 4, 3)
    assert intent.resolve_date_phrase("3/4/2026", TODAY, day_first=False).value == date(2026, 3, 4)


def test_a_bare_day_that_does_not_exist_in_the_candidate_month_is_asked_not_guessed():
    assert intent.resolve_date_phrase("31", date(2026, 10, 8)).status == "ambiguous"  # September has 30 days
    assert intent.resolve_date_phrase("31", date(2026, 11, 8)).value == date(2026, 10, 31)


@pytest.mark.parametrize(
    "text,expected",
    [("I spent 500 on lunch", "expense"), ("paid 1200 for petrol", "expense"), ("Salary received", "income"),
     ("kharch kiye", "expense"), ("expense", "expense"), ("income", "income"), ("maybe", None),
     ("I spent and received", None)],
)
def test_transaction_type_detection_refuses_to_guess(text, expected):
    assert intent.detect_type(text) == expected


def test_extraction_is_validated_against_the_schema():
    class Provider:
        def __init__(self, result):
            self.result = result

        def generate_structured(self, **_):
            return self.result

    ok = intent.extract(Provider({"transaction_type": "expense", "amount_text": "5", "unexpected": "ignored"}), "x")
    assert ok.amount_text == "5" and ok.transaction_type == "expense"
    for bad in ({"transaction_type": "transfer"}, {"transaction_type": "expense", "payment_method": "barter"},
                {"transaction_type": "expense", "amount_text": {"nested": 1}}):
        with pytest.raises(AIInvalidResponse):
            intent.extract(Provider(bad), "x")


def test_user_text_limits():
    assert intent.clean_user_text("  hello   world ") == "hello world"
    for bad in ("", "   ", "x" * 501):
        with pytest.raises(ValidationFailed):
            intent.clean_user_text(bad)


def test_category_matching_only_suggests_active_categories_of_the_right_kind():
    cats = [SimpleNamespace(name="Food & Dining", kind="expense", is_archived=False),
            SimpleNamespace(name="Fuel", kind="expense", is_archived=True),
            SimpleNamespace(name="Salary", kind="income", is_archived=False),
            SimpleNamespace(name="Pets", kind="expense", is_archived=False)]
    assert intent.match_category("chai", cats, "expense").name == "Food & Dining"
    assert intent.match_category("petrol", cats, "expense") is None  # Fuel is archived
    assert intent.match_category("salary", cats, "expense") is None  # wrong kind
    assert intent.match_category("pets", cats, "expense").name == "Pets"  # the user's own wording wins
    assert intent.match_category("", cats, "expense") is None and intent.match_category("zzz", cats, None) is None
