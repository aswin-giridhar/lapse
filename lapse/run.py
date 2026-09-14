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

    model = build_model()
    provider = active_provider()
    emit("provider", f"{provider.name} / {provider.model_id} ({provider.detail})")

    adjudications: list[Adjudication] = []

    for doc in docs:
        emit("detect", doc.doc_id)
        found = detect_clocks(doc, today, model)
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

    # Only live clocks are worth arguing about. A lapsed one is a fact, not a
    # dispute -- and spending model calls on it would be spending them on
    # something no answer can change.
    for adj in adjudications:
        if adj.clock.status is ClockStatus.LAPSED:
            continue
        emit("challenge", adj.clock.finding.right_summary)
        adj.challenge = challenge_clock(adj.clock, model)
        emit(
            "challenge.result",
            f"{'DEFEATS' if adj.challenge.defeats_claim else 'survives'} "
            f"({adj.challenge.confidence}): {adj.challenge.argument[:120]}",
        )
        emit("rebut", adj.clock.finding.right_summary)
        adj.rebuttal = rebut_challenge(adj.clock, adj.challenge, model)
        emit(
            "rebut.result",
            f"{'holds' if adj.rebuttal.survives else 'conceded'}: "
            f"{adj.rebuttal.answer[:120]}",
        )

    emit("triage", f"{len(adjudications)} clocks, budget {budget}")
    adjudications = triage(
        adjudications, today, model, budget=budget, attention_floor_usd=attention_floor_usd
    )

    return RunReport(
        today=today,
        provider=f"{provider.name} / {provider.model_id}",
        adjudications=adjudications,
    )
