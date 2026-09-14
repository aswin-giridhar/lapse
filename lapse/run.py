"""The quiet run.

This is what Lapse does when nobody is watching: read everything that
arrived, work out what it silently started, argue both sides of each one, and
then -- almost always -- say nothing.

Pipeline, per document:

    detect  ->  date  ->  challenge  ->  rebut  ->  triage
    (agent)   (Python)     (agent)      (agent)    (agent)

The dating step sits deliberately between the first two agents. The detector
proposes which clock applies; Python decides when it closes. No date that
reaches a user was produced by token generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date
from typing import Callable, Iterable

from lapse.agents import challenge_clock, detect_clocks, rebut_challenge, triage
from lapse.corpus import Document, load_inbox
from lapse.dates import compute_expiry, days_remaining, parse_date
from lapse.models import (
    Adjudication,
    Challenge,
    ClockFinding,
    ClockStatus,
    DatedClock,
    Disposition,
)
from lapse.providers import active_provider, build_model


def date_the_clock(finding: ClockFinding, today: str) -> DatedClock:
    """Attach a computed expiry to a finding. Pure Python, never the model."""
    expiry = compute_expiry(
        parse_date(finding.trigger_date), finding.window_days, finding.business_days
    )
    left = days_remaining(expiry, parse_date(today))
    return DatedClock(
        finding=finding,
        expiry_date=expiry.isoformat(),
        days_remaining=left,
        status=ClockStatus.LIVE if left >= 0 else ClockStatus.LAPSED,
    )


@dataclass
class RunReport:
    today: str
    provider: str
    adjudications: list[Adjudication] = field(default_factory=list)

    @property
    def surfaced(self) -> list[Adjudication]:
        return [a for a in self.adjudications if _disp(a) is Disposition.SURFACED]

    @property
    def withheld(self) -> list[Adjudication]:
        return [a for a in self.adjudications if _disp(a) is Disposition.WITHHELD]

    @property
    def defeated(self) -> list[Adjudication]:
        return [a for a in self.adjudications if _disp(a) is Disposition.DEFEATED]

    @property
    def lapsed(self) -> list[Adjudication]:
        return [a for a in self.adjudications if _disp(a) is Disposition.LAPSED]


def _disp(a: Adjudication) -> Disposition | None:
    return a.decision.disposition if a.decision is not None else None


def quiet_run(
    documents: Iterable[Document] | None = None,
    today: str | None = None,
    budget: int = 1,
    attention_floor_usd: float = 100.0,
    on_event: Callable[[str, str], None] | None = None,
) -> RunReport:
    """Run the full pipeline over the inbox.

    Args:
        documents: Documents to examine. Defaults to the corpus inbox.
        today: ISO date to measure against. Defaults to the system date.
        budget: How many items triage may surface.
        attention_floor_usd: Below this, a claim is generally not worth an
            interruption.
        on_event: Optional progress callback, receiving (stage, message).
    """
    today = today or _date.today().isoformat()
    docs = list(documents) if documents is not None else load_inbox()
    emit = on_event or (lambda stage, msg: None)

    # Detection is an extraction task and wants determinism: the same document
    # must not yield a clock on one run and nothing on the next, or the user
    # cannot trust the silence. Argument is a generation task and is allowed a
    # little more room.
    detect_model = build_model(temperature=0.0)
    argue_model = build_model(temperature=0.3)
    model = argue_model
    provider = active_provider()
    emit("provider", f"{provider.name} / {provider.model_id} ({provider.detail})")

    adjudications: list[Adjudication] = []
    source_by_clock: dict[int, str] = {}

    for doc in docs:
        emit("detect", doc.doc_id)
        found = detect_clocks(doc, today, detect_model)
        if not found.findings:
            emit("detect.none", f"{doc.doc_id}: {found.no_clock_reason}")
            continue
        for finding in found.findings:
            clock = date_the_clock(finding, today)
            emit(
                "clock",
                f"{finding.right_summary} -> closes {clock.expiry_date} "
                f"({clock.days_remaining}d, {clock.status.value})",
            )
            adjudications.append(Adjudication(clock=clock))
            source_by_clock[id(adjudications[-1])] = doc.text

    # Only live clocks are worth arguing about. A lapsed one is a fact, not a
    # dispute -- and spending model calls on it would be spending them on
    # something no answer can change.
    for adj in adjudications:
        if adj.clock.status is ClockStatus.LAPSED:
            continue
        emit("challenge", adj.clock.finding.right_summary)
        source = source_by_clock.get(id(adj), "")
        adj.challenge = challenge_clock(adj.clock, argue_model, source)

        # A deterministic override on the newest and least-defended path.
        # Timeliness is not a matter of opinion here: Python already computed
        # whether this window is open. If the counterparty argues the claim is
        # out of time while the clock is demonstrably live, the argument is
        # void -- and the advocate must never see it, because a weak advocate
        # concedes to a confident falsehood.
        if (
            (adj.challenge.ground == "untimely" or adj.challenge.asserts_window_has_run)
            and adj.clock.status is ClockStatus.LIVE
        ):
            emit(
                "challenge.void",
                f"counterparty argued the window has run; it closes "
                f"{adj.clock.expiry_date}, {adj.clock.days_remaining} days away "
                f"-- argument void",
            )
            adj.challenge = Challenge(
                ground="none",
                defeats_claim=False,
                argument=(
                    "The counterparty argued the claim was out of time. The "
                    f"window closes {adj.clock.expiry_date}, "
                    f"{adj.clock.days_remaining} days from now, so the argument "
                    "is void on the computed record."
                ),
                authority="Computed from the trigger date and the governing window.",
                confidence="weak",
            )
        emit(
            "challenge.result",
            f"{'DEFEATS' if adj.challenge.defeats_claim else 'survives'} "
            f"({adj.challenge.confidence}): {adj.challenge.argument[:120]}",
        )
        emit("rebut", adj.clock.finding.right_summary)
        adj.rebuttal = rebut_challenge(adj.clock, adj.challenge, argue_model, source)
        emit(
            "rebut.result",
            f"{'holds' if adj.rebuttal.survives else 'conceded'}: "
            f"{adj.rebuttal.answer[:120]}",
        )

    emit("triage", f"{len(adjudications)} clocks, budget {budget}")
    adjudications = triage(
        adjudications, today, detect_model, budget=budget, attention_floor_usd=attention_floor_usd
    )

    return RunReport(
        today=today,
        provider=f"{provider.name} / {provider.model_id}",
        adjudications=adjudications,
    )
