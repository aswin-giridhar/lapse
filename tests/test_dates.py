"""Deterministic date arithmetic -- the correctness claim of the whole project.

Every assertion here is about pure Python. Nothing in this file touches a
model, a network, or the filesystem.
"""

from __future__ import annotations

from datetime import date

import pytest

from lapse.dates import (
    _HOLIDAYS_2026,
    add_business_days,
    add_calendar_days,
    compute_expiry,
    days_remaining,
    is_business_day,
    parse_date,
)

TODAY = date(2026, 9, 14)  # the demo's "today", a Monday


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------


def test_parse_date_round_trips_iso():
    assert parse_date("2026-09-14") == date(2026, 9, 14)


def test_parse_date_tolerates_surrounding_whitespace():
    assert parse_date("  2026-09-14\n") == date(2026, 9, 14)


def test_parse_date_rejects_non_iso():
    with pytest.raises(ValueError):
        parse_date("09/14/2026")


# --------------------------------------------------------------------------
# business-day predicate
# --------------------------------------------------------------------------


def test_weekend_is_not_a_business_day():
    assert not is_business_day(date(2026, 9, 5))   # Saturday
    assert not is_business_day(date(2026, 9, 6))   # Sunday
    assert is_business_day(date(2026, 9, 4))       # Friday


def test_labor_day_2026_is_a_monday_and_is_not_a_business_day():
    labor_day = date(2026, 9, 7)
    assert labor_day.weekday() == 0, "Labor Day 2026 must be a Monday for this test to bite"
    assert labor_day in _HOLIDAYS_2026
    assert not is_business_day(labor_day)


@pytest.mark.parametrize("holiday", sorted(_HOLIDAYS_2026))
def test_every_registered_holiday_is_not_a_business_day(holiday):
    assert not is_business_day(holiday)


# --------------------------------------------------------------------------
# add_business_days
# --------------------------------------------------------------------------


def test_counting_starts_the_first_business_day_after_the_trigger():
    """The documented convention: the trigger day itself is never counted.

    Tuesday 2026-09-15 + 1 business day is Wednesday 2026-09-16, not Tuesday.
    """
    trigger = date(2026, 9, 15)
    assert trigger.weekday() == 1  # Tuesday, an ordinary business day
    assert add_business_days(trigger, 1) == date(2026, 9, 16)
    assert add_business_days(trigger, 1) != trigger


def test_zero_business_days_returns_the_trigger_itself():
    assert add_business_days(date(2026, 9, 15), 0) == date(2026, 9, 15)


def test_zero_business_days_does_not_advance_off_a_weekend():
    """Documenting real behaviour: a zero window is returned unmoved, even on
    a Saturday. The loop only runs while `remaining > 0`."""
    saturday = date(2026, 9, 5)
    assert add_business_days(saturday, 0) == saturday


def test_single_business_day_crosses_a_weekend():
    """Friday + 1 business day lands on the following Monday, not Saturday."""
    friday = date(2026, 9, 11)
    assert friday.weekday() == 4
    assert add_business_days(friday, 1) == date(2026, 9, 14)  # Monday


def test_crossing_labor_day_skips_the_holiday():
    """Friday 2026-09-04 + 1 business day is Tuesday 2026-09-08.

    This assertion is discriminating: with weekends skipped but holidays
    ignored the answer would be Monday 2026-09-07 (Labor Day). If
    _HOLIDAYS_2026 were emptied, this test goes red.
    """
    friday = date(2026, 9, 4)
    assert friday.weekday() == 4
    assert add_business_days(friday, 1) == date(2026, 9, 8)
    assert add_business_days(friday, 1) != date(2026, 9, 7)


def test_window_spanning_labor_day_week_is_one_day_longer_than_the_weekend_only_answer():
    """Wed 2026-09-02 + 5 business days -> Thu 2026-09-10.

    Skipping weekends but not holidays would give Wed 2026-09-09; the extra
    day is Labor Day.
    """
    assert add_business_days(date(2026, 9, 2), 5) == date(2026, 9, 10)
    assert add_business_days(date(2026, 9, 2), 5) != date(2026, 9, 9)


def test_negative_business_day_window_raises_value_error():
    with pytest.raises(ValueError):
        add_business_days(date(2026, 9, 14), -1)


def test_business_day_result_is_always_itself_a_business_day():
    for n in range(1, 30):
        assert is_business_day(add_business_days(date(2026, 9, 2), n))


# --------------------------------------------------------------------------
# add_calendar_days / compute_expiry dispatch
# --------------------------------------------------------------------------


def test_add_calendar_days_counts_the_trigger_as_day_zero():
    assert add_calendar_days(date(2026, 9, 14), 0) == date(2026, 9, 14)
    assert add_calendar_days(date(2026, 9, 14), 1) == date(2026, 9, 15)


def test_add_calendar_days_does_not_skip_weekends_or_holidays():
    # Friday + 3 calendar days is Monday Labor Day, untouched by the calendar.
    assert add_calendar_days(date(2026, 9, 4), 3) == date(2026, 9, 7)


def test_compute_expiry_dispatches_to_calendar_by_default():
    assert compute_expiry(date(2026, 9, 4), 10) == add_calendar_days(date(2026, 9, 4), 10)
    assert compute_expiry(date(2026, 9, 4), 10, business_days=False) == date(2026, 9, 14)


def test_compute_expiry_dispatches_to_business_days_when_asked():
    assert compute_expiry(date(2026, 9, 4), 10, business_days=True) == add_business_days(
        date(2026, 9, 4), 10
    )


def test_compute_expiry_branches_actually_differ_for_the_same_input():
    """If dispatch were broken and both branches went to the same function,
    these two would agree. Over a window spanning weekends they must not."""
    trigger, window = date(2026, 9, 4), 10
    assert compute_expiry(trigger, window, business_days=True) != compute_expiry(
        trigger, window, business_days=False
    )


def test_compute_expiry_propagates_the_negative_business_window_error():
    with pytest.raises(ValueError):
        compute_expiry(date(2026, 9, 14), -1, business_days=True)


def test_compute_expiry_rejects_a_negative_window_on_both_paths():
    """Both paths now refuse a backwards window.

    The calendar path used to return a date in the past, which would present a
    fabricated deadline as an already-lapsed one -- a silent wrong answer where
    the business path raised loudly. Symmetry here is a correctness property,
    not tidiness.
    """
    with pytest.raises(ValueError):
        compute_expiry(date(2026, 9, 14), -1, business_days=False)
    with pytest.raises(ValueError):
        compute_expiry(date(2026, 9, 14), -1, business_days=True)


# --------------------------------------------------------------------------
# days_remaining
# --------------------------------------------------------------------------


def test_days_remaining_is_zero_on_the_expiry_date_itself():
    assert days_remaining(date(2026, 9, 14), date(2026, 9, 14)) == 0


def test_days_remaining_is_positive_before_expiry():
    assert days_remaining(date(2026, 9, 20), TODAY) == 6


def test_days_remaining_is_negative_once_lapsed():
    assert days_remaining(date(2026, 9, 13), TODAY) == -1
    assert days_remaining(date(2026, 8, 31), TODAY) == -14


# --------------------------------------------------------------------------
# REGRESSION: the five real corpus scenarios the demo depends on.
# A silent change to any of these values breaks the demo.
# --------------------------------------------------------------------------

CORPUS_SCENARIOS = [
    # (label, trigger, window, business_days, expected_expiry, expected_days_left)
    ("keystone_insurance_appeal", "2026-03-29", 180, False, "2026-09-25", 11),
    ("meridian_scope_objection", "2026-09-08", 10, True, "2026-09-22", 8),
    ("brightwater_habitability", "2026-09-02", 14, False, "2026-09-16", 2),
    ("safenest_recall", "2026-08-20", 90, False, "2026-11-18", 65),
    ("northgate_price_protection", "2026-08-01", 30, False, "2026-08-31", -14),
]


@pytest.mark.parametrize(
    "label,trigger,window,business,expected_expiry,expected_left",
    CORPUS_SCENARIOS,
    ids=[s[0] for s in CORPUS_SCENARIOS],
)
def test_corpus_scenario_regression(
    label, trigger, window, business, expected_expiry, expected_left
):
    expiry = compute_expiry(parse_date(trigger), window, business)
    assert expiry.isoformat() == expected_expiry, label
    assert days_remaining(expiry, TODAY) == expected_left, label


def test_northgate_scenario_is_the_lapsed_one():
    expiry = compute_expiry(parse_date("2026-08-01"), 30, False)
    assert days_remaining(expiry, TODAY) < 0


def test_the_other_four_corpus_scenarios_are_live():
    for label, trigger, window, business, _expiry, _left in CORPUS_SCENARIOS[:-1]:
        expiry = compute_expiry(parse_date(trigger), window, business)
        assert days_remaining(expiry, TODAY) >= 0, label
