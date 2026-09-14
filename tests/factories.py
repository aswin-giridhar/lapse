"""Builders for the typed payloads, so tests can construct pipeline state
without running any agent."""

from __future__ import annotations

from typing import Optional

from lapse.models import (
    Adjudication,
    Challenge,
    ClockFinding,
    ClockStatus,
    DatedClock,
    Rebuttal,
)


def make_finding(
    *,
    trigger_date: str = "2026-09-01",
    window_days: int = 30,
    business_days: bool = False,
    value_usd: Optional[float] = None,
    doc_id: str = "test_doc.txt",
    clock_kind: str = "retail_return",
) -> ClockFinding:
    return ClockFinding(
        doc_id=doc_id,
        clock_kind=clock_kind,
        right_summary="A test right that expires.",
        counterparty="Test Counterparty Inc.",
        trigger_date=trigger_date,
        trigger_quote="...the window opens on the date of this notice...",
        window_days=window_days,
        business_days=business_days,
        authority="The test instrument, clause 1.",
        value_usd=value_usd,
        value_basis="fixture",
    )


def make_adjudication(
    *,
    days_remaining: int,
    value_usd: Optional[float],
    status: ClockStatus = ClockStatus.LIVE,
    survives: bool = True,
    with_rebuttal: bool = True,
    expiry_date: str = "2026-09-16",
    summary: str = "A test right that expires.",
) -> Adjudication:
    """Build a fully-formed Adjudication as it would look entering triage."""
    finding = make_finding(value_usd=value_usd)
    finding = finding.model_copy(update={"right_summary": summary})
    clock = DatedClock(
        finding=finding,
        expiry_date=expiry_date,
        days_remaining=days_remaining,
        status=status,
    )
    rebuttal = (
        Rebuttal(
            survives=survives,
            answer="The challenge fails because the clause says otherwise."
            if survives
            else "Conceded: the counterparty is right.",
            authority="Clause 4.2",
            drafted_action="Dear sir or madam, ..." if survives else "",
        )
        if with_rebuttal
        else None
    )
    return Adjudication(
        clock=clock,
        challenge=Challenge(
            defeats_claim=not survives,
            argument="You are out of time.",
            authority="Clause 9",
            confidence="arguable",
        ),
        rebuttal=rebuttal,
    )
