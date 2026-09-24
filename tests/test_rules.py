"""Tests for the detection rules.

The headline false-positive number rests entirely on these functions being
correct, so the window boundaries are tested explicitly rather than assumed.
"""
import numpy as np
import pandas as pd
import pytest

import rules
from timeutils import epoch_ns
from conftest import txn

DAY = 24.0


# --------------------------------------------------------------------------
# _window_counts - the burst detector underneath the structuring rule
# --------------------------------------------------------------------------

def _burst(offsets_days, window_days=7, min_count=3):
    # epoch_ns, not .astype("int64"): the helper has to normalise the datetime
    # unit for the same reason the rules do, or it silently builds an infinitely
    # wide window on pandas 3 and every assertion here passes for free.
    times = pd.Timestamp("2025-01-01") + pd.to_timedelta(offsets_days, unit="D")
    return list(rules._in_burst(np.sort(epoch_ns(times)),
                                int(pd.Timedelta(days=window_days).value),
                                min_count))


def test_in_burst_flags_every_member_including_the_middle():
    # Regression: an earlier version scored each event only against windows
    # anchored at it, so the middle payment of a three-payment burst scored 2
    # and escaped. Every member of the cluster must flag.
    assert _burst([0, 2, 4]) == [True, True, True]


def test_in_burst_flags_the_interior_of_a_longer_run():
    assert _burst([0, 1, 2, 3, 4]) == [True] * 5


def test_in_burst_ignores_events_spread_beyond_the_window():
    assert _burst([0, 20, 40]) == [False, False, False]


def test_in_burst_needs_the_full_count():
    assert _burst([0, 1]) == [False, False]


def test_in_burst_boundary_is_inclusive():
    assert _burst([0, 7], min_count=2) == [True, True]
    assert _burst([0, 7.001], min_count=2) == [False, False]


def test_in_burst_does_not_leak_across_a_gap():
    # A tight cluster and one far-away straggler: the straggler must not inherit
    # the cluster's flag.
    assert _burst([0, 1, 2, 60]) == [True, True, True, False]


# --------------------------------------------------------------------------
# rule_structuring
# --------------------------------------------------------------------------

def test_structuring_flags_three_near_threshold_payments_in_a_week(frame):
    df = frame([txn(amount=9_500, offset_hours=d * DAY) for d in (0, 1, 2)])
    assert rules.rule_structuring(df).all()


def test_structuring_ignores_the_same_payments_spread_over_a_month(frame):
    df = frame([txn(amount=9_500, offset_hours=d * DAY) for d in (0, 15, 30)])
    assert not rules.rule_structuring(df).any()


def test_structuring_needs_three_not_two(frame):
    df = frame([txn(amount=9_500, offset_hours=d * DAY) for d in (0, 1)])
    assert not rules.rule_structuring(df).any()


def test_structuring_ignores_amounts_below_the_band(frame):
    # £5,000 is under 70% of the £10,000 threshold - not threshold-hugging.
    df = frame([txn(amount=5_000, offset_hours=d * DAY) for d in (0, 1, 2)])
    assert not rules.rule_structuring(df).any()


def test_structuring_ignores_amounts_over_the_threshold(frame):
    # Above £10,000 it gets reported anyway - structuring is about staying under.
    df = frame([txn(amount=10_500, offset_hours=d * DAY) for d in (0, 1, 2)])
    assert not rules.rule_structuring(df).any()


def test_structuring_catches_funnelling_into_one_beneficiary(frame):
    # Three DIFFERENT senders paying one receiver: no sender repeats, so a
    # sender-only rule sees nothing. This is the shape found in the real data.
    df = frame([txn(sender=f"ACC{i}", receiver="MULE", amount=9_400,
                    offset_hours=i * DAY) for i in (1, 2, 3)])
    assert rules.rule_structuring(df).all()


def test_structuring_does_not_flag_unrelated_accounts_in_the_same_window(frame):
    # Three near-threshold payments in one week, but no shared counterparty.
    df = frame([txn(sender=f"S{i}", receiver=f"R{i}", amount=9_400,
                    offset_hours=i * DAY) for i in (1, 2, 3)])
    assert not rules.rule_structuring(df).any()


# --------------------------------------------------------------------------
# rule_rapid_movement
# --------------------------------------------------------------------------

def test_rapid_movement_flags_money_in_then_straight_out(frame):
    df = frame([
        txn(sender="SRC", receiver="MULE", amount=20_000, offset_hours=0),
        txn(sender="MULE", receiver="DEST", amount=19_000, offset_hours=6),
    ])
    assert rules.rule_rapid_movement(df).all(), "both legs of the pair should flag"


def test_rapid_movement_ignores_an_outflow_after_the_window(frame):
    df = frame([
        txn(sender="SRC", receiver="MULE", amount=20_000, offset_hours=0),
        txn(sender="MULE", receiver="DEST", amount=19_000, offset_hours=25),
    ])
    assert not rules.rule_rapid_movement(df).any()


def test_rapid_movement_window_boundary_is_inclusive(frame):
    df = frame([
        txn(sender="SRC", receiver="MULE", amount=20_000, offset_hours=0),
        txn(sender="MULE", receiver="DEST", amount=19_000, offset_hours=24),
    ])
    assert rules.rule_rapid_movement(df).all()


def test_rapid_movement_ignores_a_partial_outflow(frame):
    # Half the money leaving is ordinary spending, not pass-through.
    df = frame([
        txn(sender="SRC", receiver="MULE", amount=20_000, offset_hours=0),
        txn(sender="MULE", receiver="DEST", amount=10_000, offset_hours=6),
    ])
    assert not rules.rule_rapid_movement(df).any()


def test_rapid_movement_sums_several_small_outflows(frame):
    # Splitting the exit does not evade the rule.
    df = frame([txn(sender="SRC", receiver="MULE", amount=20_000, offset_hours=0)] +
               [txn(sender="MULE", receiver=f"D{i}", amount=5_500, offset_hours=i + 1)
                for i in range(3)])
    assert rules.rule_rapid_movement(df).all()


def test_rapid_movement_requires_the_outflow_to_follow_the_inflow(frame):
    # Same amounts, reversed order: paying out and being reimbursed later is
    # not pass-through. Direction is the whole point of the rule.
    df = frame([
        txn(sender="MULE", receiver="DEST", amount=19_000, offset_hours=0),
        txn(sender="SRC", receiver="MULE", amount=20_000, offset_hours=6),
    ])
    assert not rules.rule_rapid_movement(df).any()


def test_rapid_movement_ignores_small_credits(frame):
    # Below the £1,000 floor: everyday balances churn, and flagging them is
    # exactly the noise this project exists to remove.
    df = frame([
        txn(sender="SRC", receiver="MULE", amount=500, offset_hours=0),
        txn(sender="MULE", receiver="DEST", amount=480, offset_hours=1),
    ])
    assert not rules.rule_rapid_movement(df).any()


# --------------------------------------------------------------------------
# rule_high_risk_country / rule_round_amount
# --------------------------------------------------------------------------

@pytest.mark.parametrize("sender_country,receiver_country,expected", [
    ("United Kingdom", "United Kingdom", False),
    ("Panama", "United Kingdom", True),
    ("United Kingdom", "Seychelles", True),
    ("Cyprus", "Malta", True),
])
def test_high_risk_country_checks_both_legs(frame, sender_country,
                                            receiver_country, expected):
    df = frame([txn(sender_country=sender_country, receiver_country=receiver_country)])
    assert bool(rules.rule_high_risk_country(df).iloc[0]) is expected


@pytest.mark.parametrize("amount,expected", [
    (5_000.00, True),     # exact whole pound at size
    (5_000.37, False),    # organic-looking
    (500.00, False),      # whole pound but below the £1,000 floor
    (1_000.00, True),     # exactly at the floor
])
def test_round_amount(frame, amount, expected):
    df = frame([txn(amount=amount)])
    assert bool(rules.rule_round_amount(df).iloc[0]) is expected


# --------------------------------------------------------------------------
# apply_all
# --------------------------------------------------------------------------

def test_apply_all_reports_every_rule_and_counts_overlaps(frame):
    # One transaction that trips two rules at once.
    df = frame([txn(amount=9_000.00, sender_country="Panama", offset_hours=0)])
    fired = rules.apply_all(df)
    assert set(rules.RULES) <= set(fired.columns)
    assert fired.loc[0, "rules_fired"] == 2          # high_risk_country + round_amount
    assert fired.loc[0, "rule_alert"]
    assert rules.reason_text(fired.iloc[0]) == "high_risk_country, round_amount"


def test_apply_all_leaves_ordinary_transactions_alone(frame):
    df = frame([txn(amount=247.53, offset_hours=h) for h in range(5)])
    assert not rules.apply_all(df)["rule_alert"].any()


# --------------------------------------------------------------------------
# datetime unit independence
#
# pandas 2 reads timestamps as datetime64[ns], pandas 3 as datetime64[us].
# Casting either straight to int64 and comparing against a nanosecond window
# makes every window 1000x too wide on one of them - silently, with no error.
# These pin the behaviour to be identical under both units.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("unit", ["ns", "us", "ms", "s"])
def test_structuring_is_independent_of_datetime_unit(frame, unit):
    rows = [txn(amount=9_500, offset_hours=d * DAY) for d in (0, 1, 2)]
    # Spread out, and with their own counterparties so the beneficiary-side
    # rule has nothing to cluster on either: these must NOT flag.
    rows += [txn(sender="OTHER", receiver="OTHER_R", amount=9_500,
                 offset_hours=d * DAY) for d in (0, 40, 80)]
    df = frame(rows)
    df["timestamp"] = df["timestamp"].astype(f"datetime64[{unit}]")
    fired = rules.rule_structuring(df)
    assert fired.sum() == 3, f"unit {unit} changed the structuring result"


@pytest.mark.parametrize("unit", ["ns", "us", "ms", "s"])
def test_rapid_movement_is_independent_of_datetime_unit(frame, unit):
    df = frame([
        txn(sender="SRC", receiver="MULE", amount=20_000, offset_hours=0),
        txn(sender="MULE", receiver="DEST", amount=19_000, offset_hours=6),
        # A second pair outside the window, which must stay unflagged.
        txn(sender="SRC2", receiver="MULE2", amount=20_000, offset_hours=100),
        txn(sender="MULE2", receiver="DEST2", amount=19_000, offset_hours=140),
    ])
    df["timestamp"] = df["timestamp"].astype(f"datetime64[{unit}]")
    fired = rules.rule_rapid_movement(df)
    assert fired.sum() == 2, f"unit {unit} changed the rapid-movement result"


@pytest.mark.parametrize("unit", ["ns", "us"])
def test_window_boundary_holds_under_both_units(frame, unit):
    # Exactly 24h apart is inside the window; 25h is outside.
    for hours, expected in ((24, 2), (25, 0)):
        df = frame([
            txn(sender="SRC", receiver="MULE", amount=20_000, offset_hours=0),
            txn(sender="MULE", receiver="DEST", amount=19_000, offset_hours=hours),
        ])
        df["timestamp"] = df["timestamp"].astype(f"datetime64[{unit}]")
        assert rules.rule_rapid_movement(df).sum() == expected
