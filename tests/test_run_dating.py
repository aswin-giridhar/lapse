"""`date_the_clock` -- the Python step wedged between two agents.

The status boundary matters: a clock with exactly zero days left is still
LIVE (you can act today), and only becomes LAPSED at -1.
"""

from __future__ import annotations

import pytest

from lapse.models import ClockStatus
from lapse.run import date_the_clock

from tests.factories import make_finding

TODAY = "2026-09-14"


def test_expiry_and_days_remaining_are_computed_not_guessed():
    clock = date_the_clock(make_finding(trigger_date="2026-03-29", window_days=180), TODAY)
    assert clock.expiry_date == "2026-09-25"
    assert clock.days_remaining == 11
    assert clock.status is ClockStatus.LIVE


def test_business_day_findings_use_the_business_day_calendar():
    clock = date_the_clock(
        make_finding(trigger_date="2026-09-08", window_days=10, business_days=True), TODAY
    )
    assert clock.expiry_date == "2026-09-22"
    assert clock.days_remaining == 8
    assert clock.status is ClockStatus.LIVE


def test_status_is_live_at_exactly_zero_days_remaining():
    """Boundary pin: expiring today is not expired."""
    clock = date_the_clock(make_finding(trigger_date="2026-09-04", window_days=10), TODAY)
    assert clock.expiry_date == TODAY
    assert clock.days_remaining == 0
    assert clock.status is ClockStatus.LIVE


def test_status_is_lapsed_at_minus_one_day():
    clock = date_the_clock(make_finding(trigger_date="2026-09-03", window_days=10), TODAY)
    assert clock.days_remaining == -1
    assert clock.status is ClockStatus.LAPSED


def test_status_is_lapsed_for_the_northgate_scenario():
    clock = date_the_clock(make_finding(trigger_date="2026-08-01", window_days=30), TODAY)
    assert clock.expiry_date == "2026-08-31"
    assert clock.days_remaining == -14
    assert clock.status is ClockStatus.LAPSED


def test_the_finding_is_carried_through_unchanged():
    finding = make_finding(trigger_date="2026-09-02", window_days=14)
    clock = date_the_clock(finding, TODAY)
    assert clock.finding == finding


@pytest.mark.parametrize(
    "trigger,window,business,expiry,left,status",
    [
        ("2026-03-29", 180, False, "2026-09-25", 11, ClockStatus.LIVE),
        ("2026-09-08", 10, True, "2026-09-22", 8, ClockStatus.LIVE),
        ("2026-09-02", 14, False, "2026-09-16", 2, ClockStatus.LIVE),
        ("2026-08-20", 90, False, "2026-11-18", 65, ClockStatus.LIVE),
        ("2026-08-01", 30, False, "2026-08-31", -14, ClockStatus.LAPSED),
    ],
)
def test_corpus_scenarios_end_to_end_through_the_dating_step(
    trigger, window, business, expiry, left, status
):
    clock = date_the_clock(
        make_finding(trigger_date=trigger, window_days=window, business_days=business),
        TODAY,
    )
    assert (clock.expiry_date, clock.days_remaining, clock.status) == (expiry, left, status)
