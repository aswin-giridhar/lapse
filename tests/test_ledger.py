"""Tests for cross-run memory.

The ledger shipped with none, while 120 tests passed elsewhere -- which is its
own kind of false signal about how well covered this project is.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lapse.ledger import Entry, Ledger, LedgerUnreadable, clock_identity
from lapse.models import (
    Adjudication,
    ClockFinding,
    ClockStatus,
    DatedClock,
    Decision,
    Disposition,
)


def make_adj(
    doc_id: str = "a.txt",
    counterparty: str = "Keystone Mutual Health",
    clock_kind: str = "insurance_internal_appeal",
    trigger_date: str = "2026-03-29",
    window_days: int = 180,
    summary: str = "Appeal the denial",
) -> Adjudication:
    f = ClockFinding(
        doc_id=doc_id,
        clock_kind=clock_kind,
        right_summary=summary,
        counterparty=counterparty,
        trigger_date=trigger_date,
        trigger_quote="q",
        window_days=window_days,
        authority="plan",
    )
    c = DatedClock(
        finding=f, expiry_date="2026-09-25", days_remaining=11, status=ClockStatus.LIVE
    )
    return Adjudication(
        clock=c, decision=Decision(disposition=Disposition.SURFACED, reason="r")
    )


@pytest.fixture
def ledger(tmp_path: Path) -> Ledger:
    return Ledger(path=tmp_path / "state.json")


def test_the_same_letter_arriving_as_two_files_is_one_clock():
    """The case the module exists for.

    Identity previously included the model-generated doc_id, so the same
    denial arriving twice created two clocks and asked the user twice.
    """
    assert clock_identity(make_adj(doc_id="denial.txt")) == clock_identity(
        make_adj(doc_id="denial_COPY (1).txt")
    )


def test_a_reworded_summary_is_still_the_same_clock():
    """Summaries are model-written and drift between runs."""
    assert clock_identity(make_adj(summary="Appeal the denial")) == clock_identity(
        make_adj(summary="Right to request review of an adverse determination")
    )


def test_genuinely_different_clocks_get_different_ids():
    base = clock_identity(make_adj())
    assert clock_identity(make_adj(counterparty="Other Insurer")) != base
    assert clock_identity(make_adj(trigger_date="2026-04-01")) != base
    assert clock_identity(make_adj(clock_kind="retail_return")) != base
    assert clock_identity(make_adj(window_days=60)) != base


def test_second_sighting_is_not_new_and_increments(ledger: Ledger):
    adj = make_adj()
    _, first = ledger.record(adj, "2026-09-14")
    entry, second = ledger.record(adj, "2026-09-15")
    assert first is True and second is False
    assert entry.times_seen == 2
    assert entry.first_seen == "2026-09-14" and entry.last_seen == "2026-09-15"


def test_snooze_mutes_until_the_date_then_stops(ledger: Ledger):
    entry, _ = ledger.record(make_adj(), "2026-09-14")
    ledger.act(entry.clock_id, "snoozed", until="2026-09-20")
    assert entry.is_muted_on("2026-09-19")[0] is True
    assert entry.is_muted_on("2026-09-20")[0] is False


def test_a_snooze_without_a_date_is_refused(ledger: Ledger):
    """Otherwise it creates a snooze that silently never mutes anything."""
    entry, _ = ledger.record(make_adj(), "2026-09-14")
    with pytest.raises(ValueError):
        ledger.act(entry.clock_id, "snoozed", until=None)


def test_a_note_does_not_wipe_a_live_snooze(ledger: Ledger):
    entry, _ = ledger.record(make_adj(), "2026-09-14")
    ledger.act(entry.clock_id, "snoozed", until="2026-09-20")
    ledger.act(entry.clock_id, "snoozed", until="2026-09-20", note="ringing them")
    assert entry.snoozed_until == "2026-09-20"
    assert entry.note == "ringing them"


def test_dismissal_survives_a_reload(tmp_path: Path):
    path = tmp_path / "state.json"
    first = Ledger(path=path)
    entry, _ = first.record(make_adj(), "2026-09-14")
    first.act(entry.clock_id, "dismissed")
    first.save()
    reloaded = Ledger(path=path)
    again, is_new = reloaded.record(make_adj(), "2026-09-15")
    assert is_new is False
    assert again.is_muted_on("2026-09-15") == (True, "you dismissed this")


def test_a_corrupt_ledger_raises_rather_than_starting_empty(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(LedgerUnreadable):
        Ledger(path=path)


def test_an_incompatible_schema_raises_the_right_error(tmp_path: Path):
    """Not a bare TypeError -- silently forgetting every dismissal is the
    failure this whole system is built to avoid."""
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps({"entries": {"abc": {"unexpected_field": 1}}}), encoding="utf-8"
    )
    with pytest.raises(LedgerUnreadable):
        Ledger(path=path)


def test_a_missing_ledger_is_simply_empty(tmp_path: Path):
    """Absent and broken must not look the same."""
    assert Ledger(path=tmp_path / "nothing.json").entries == {}
