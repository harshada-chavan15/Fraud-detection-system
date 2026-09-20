"""
test_risk_engine.py

Unit tests for the rule engine. They need NO database, because score_transaction()
takes plain dicts.

Run from the project folder:
    python -m pytest -v

Put this file in a folder called "tests" (recommended), or leave it next to
risk_engine.py. Either way works.
"""

import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

# Make "import risk_engine" work no matter where pytest is started from
HERE = os.path.dirname(os.path.abspath(__file__))
for path in (HERE, os.path.dirname(HERE)):
    if os.path.exists(os.path.join(path, "risk_engine.py")):
        sys.path.insert(0, path)
        break

from risk_engine import decide, distance_between, score_transaction  # noqa: E402

OLD_ACCOUNT = datetime(2025, 1, 1)
AFTERNOON = datetime(2026, 9, 15, 14, 0)   # a normal hour, so no night-time points


def make_txn(amount=500, ts=AFTERNOON, location="Pune", avg=800, created=OLD_ACCOUNT):
    """A normal, harmless transaction. Each test changes ONE thing."""
    return {
        "amount": amount,
        "timestamp": ts,
        "location": location,
        "avg_amount": avg,
        "account_created_at": created,
    }


def make_prev(location, minutes_before):
    return {"location": location, "timestamp": AFTERNOON - timedelta(minutes=minutes_before)}


# ---------------------------------------------------------------- baseline
def test_normal_transaction_scores_zero_and_is_approved():
    score, reasons = score_transaction(make_txn(), None, 1)
    assert score == 0
    assert reasons == []
    assert decide(score) == "APPROVED"


# ------------------------------------------------------------ amount rules
def test_high_amount_adds_3_points_at_exactly_the_threshold():
    score, reasons = score_transaction(make_txn(amount=10000, avg=9000), None, 1)
    assert score == 3
    assert "high amount" in reasons


def test_just_below_high_amount_adds_nothing():
    score, _ = score_transaction(make_txn(amount=9999, avg=9000), None, 1)
    assert score == 0


def test_amount_over_3x_average_adds_3_points():
    score, reasons = score_transaction(make_txn(amount=3001, avg=1000), None, 1)
    assert score == 3
    assert any("3x" in r for r in reasons)


def test_amount_exactly_3x_average_is_not_flagged():
    score, _ = score_transaction(make_txn(amount=3000, avg=1000), None, 1)
    assert score == 0


@pytest.mark.parametrize("avg", [None, 0])
def test_missing_or_zero_average_does_not_crash(avg):
    score, _ = score_transaction(make_txn(avg=avg), None, 1)
    assert score == 0


def test_decimal_values_from_mysql_are_handled():
    txn = make_txn(amount=Decimal("12000.50"), avg=Decimal("800.00"))
    score, _ = score_transaction(txn, None, 1)
    assert score == 6   # high amount (3) + above 3x average (3)


# ---------------------------------------------------------------- night rule
@pytest.mark.parametrize("hour, is_night", [
    (22, False), (23, True), (0, True), (5, True), (6, False), (14, False),
])
def test_night_hours(hour, is_night):
    ts = datetime(2026, 9, 15, hour, 30)
    score, _ = score_transaction(make_txn(ts=ts), None, 1)
    assert score == (2 if is_night else 0)


# ------------------------------------------------------------- new account
def test_new_account_is_flagged():
    created = AFTERNOON - timedelta(hours=5)
    score, reasons = score_transaction(make_txn(created=created), None, 1)
    assert score == 2
    assert any("new account" in r for r in reasons)


def test_account_older_than_48_hours_is_not_flagged():
    created = AFTERNOON - timedelta(hours=49)
    score, _ = score_transaction(make_txn(created=created), None, 1)
    assert score == 0


# --------------------------------------------------------- impossible travel
def test_impossible_travel_long_distance_short_time():
    # Bangalore -> Pune is 840 km, in 30 minutes
    score, reasons = score_transaction(make_txn(location="Pune"), make_prev("Bangalore", 30), 1)
    assert score == 5
    assert "impossible travel" in reasons[0]


def test_long_distance_with_enough_time_is_fine():
    score, _ = score_transaction(make_txn(location="Pune"), make_prev("Bangalore", 60), 1)
    assert score == 0


def test_short_trip_in_a_very_short_time_is_flagged():
    # Mumbai -> Pune is 150 km, in 10 minutes
    score, _ = score_transaction(make_txn(location="Pune"), make_prev("Mumbai", 10), 1)
    assert score == 5


def test_short_trip_with_enough_time_is_fine():
    score, _ = score_transaction(make_txn(location="Pune"), make_prev("Mumbai", 15), 1)
    assert score == 0


def test_same_city_is_never_impossible_travel():
    score, _ = score_transaction(make_txn(location="Pune"), make_prev("Pune", 1), 1)
    assert score == 0


def test_unknown_city_pair_does_not_crash():
    # This used to raise a TypeError in the first version of the project
    score, _ = score_transaction(make_txn(location="Pune"), make_prev("Delhi", 5), 1)
    assert score == 0


def test_first_ever_transaction_has_no_travel_check():
    score, _ = score_transaction(make_txn(), None, 1)
    assert score == 0


# ------------------------------------------------------------------ velocity
def test_three_transactions_in_a_minute_is_velocity():
    score, reasons = score_transaction(make_txn(), None, 3)
    assert score == 4
    assert "velocity" in reasons[0]


def test_two_transactions_in_a_minute_is_fine():
    score, _ = score_transaction(make_txn(), None, 2)
    assert score == 0


# ------------------------------------------------------------- combined + decide
def test_rules_add_up():
    ts = datetime(2026, 9, 15, 2, 0)   # night
    score, reasons = score_transaction(make_txn(amount=20000, ts=ts), None, 1)
    assert score == 3 + 2 + 3          # high amount + night + above 3x average
    assert len(reasons) == 3
    assert decide(score) == "BLOCKED"


@pytest.mark.parametrize("score, expected", [
    (0, "APPROVED"), (2, "APPROVED"),
    (3, "FLAGGED"), (5, "FLAGGED"),
    (6, "BLOCKED"), (15, "BLOCKED"),
])
def test_decision_boundaries(score, expected):
    assert decide(score) == expected


def test_distance_between():
    assert distance_between("Pune", "Pune") == 0
    assert distance_between("Pune", "Mumbai") == 150
    assert distance_between("Mumbai", "Pune") == 150   # order does not matter
    assert distance_between("Pune", "Delhi") == 0      # unknown pair -> skipped
