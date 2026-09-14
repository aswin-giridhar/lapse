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

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Lock
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
    Decision,
    Disposition,
)
from lapse.ledger import Ledger, clock_identity
from lapse.providers import active_provider, build_model
from lapse.telemetry import MetricsCollector, RunMetrics


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
    new_clock_ids: set[str] = field(default_factory=set)
    muted_count: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    metrics: RunMetrics = field(default_factory=RunMetrics)

    def is_new(self, adj: Adjudication) -> bool:
        return clock_identity(adj) in self.new_clock_ids

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
    ledger: Ledger | None = None,
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

    # Detection is an extraction task, so it runs at temperature 0 to reduce
    # variance. It does NOT make the run deterministic, and it would be
    # dishonest to imply otherwise: measured over five runs of the same six
    # documents, detection returned 4, 5, 5, 5, 6 and 6 clocks -- a 50%
    # spread on the same input. Temperature 0
    # constrains sampling, not tool-use paths or structured-output retries.
    # Recall this imperfect is the central open problem for this system --
    # a missed clock is silent, and silence is exactly what the user is being
    # asked to trust. Argument is generation and is allowed more room.
    collector = MetricsCollector()
    detect_model = build_model(temperature=0.0)
    argue_model = build_model(temperature=0.3)
    model = argue_model
    provider = active_provider()
    emit("provider", f"{provider.name} / {provider.model_id} ({provider.detail})")

    errors: list[tuple[str, str]] = []
    adjudications: list[Adjudication] = []
    # Pair each adjudication with the document it came from directly. Keying a
    # side table on id() is fragile and, worse, degrades to an empty document
    # -- which would hand the adversary nothing to argue with while looking
    # like a successful run.
    sources: list[str] = []

    emit_lock = Lock()

    def safe_emit(stage: str, message: str) -> None:
        with emit_lock:
            emit(stage, message)

    def examine(doc: Document):
        """Read one document. Documents are independent, so this parallelises."""
        safe_emit("detect", doc.doc_id)
        try:
            return doc, detect_clocks(doc, today, detect_model, hooks=[collector]), None
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            # A document that cannot be read must be announced, not skipped.
            # Silently dropping it would mean a clock the user believes is
            # being watched is not being watched at all.
            return doc, None, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(docs)))) as pool:
        examined = list(pool.map(examine, docs))

    for doc, found, error in examined:
        if error is not None:
            safe_emit("detect.error", f"{doc.doc_id}: {error}")
            errors.append((doc.doc_id, error))
            continue
        if not found.findings:
            safe_emit("detect.none", f"{doc.doc_id}: {found.no_clock_reason}")
            continue
        for finding in found.findings:
            # The filename is a fact we already know. Taking the model's echo
            # of it on trust is free to avoid and would silently corrupt every
            # ledger identity keyed on this clock.
            finding = finding.model_copy(update={"doc_id": doc.doc_id})
            clock = date_the_clock(finding, today)
            safe_emit(
                "clock",
                f"{finding.right_summary} -> closes {clock.expiry_date} "
                f"({clock.days_remaining}d, {clock.status.value})",
            )
            adjudications.append(Adjudication(clock=clock))
            sources.append(doc.text)

    # Only live clocks are worth arguing about. A lapsed one is a fact, not a
    # dispute -- and spending model calls on it would be spending them on
    # something no answer can change.
    ledger = ledger if ledger is not None else Ledger()
    muted_box = [0]

    def argue(pair) -> None:
        adj, source = pair
        try:
            _argue_one(adj, source)
        except Exception as exc:  # noqa: BLE001 - recorded, never silent
            # A clock we could not argue about must not look like a clock that
            # survived, nor vanish. Record it and let triage decide.
            safe_emit(
                "argue.error",
                f"{adj.clock.finding.right_summary}: {type(exc).__name__}: {exc}",
            )
            errors.append((adj.clock.finding.doc_id, f"argument stage: {exc}"))

    def _argue_one(adj: Adjudication, source: str) -> None:
        if adj.clock.status is ClockStatus.LAPSED:
            return
        # Respect what the user already decided, BEFORE spending model calls
        # arguing about it. Re-litigating a dismissal is the fastest way to
        # teach someone to ignore you.
        prior = ledger.entries.get(clock_identity(adj))
        if prior is not None:
            is_muted, why = prior.is_muted_on(today)
            if is_muted:
                adj.decision = Decision(
                    disposition=Disposition.WITHHELD,
                    reason=why,
                    revisit_on=prior.snoozed_until,
                )
                with emit_lock:
                    muted_box[0] += 1
                safe_emit("muted", f"{adj.clock.finding.right_summary} -- {why}")
                return
        safe_emit("challenge", adj.clock.finding.right_summary)
        adj.challenge = challenge_clock(
            adj.clock, argue_model, source, hooks=[collector]
        )

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
            safe_emit(
                "challenge.void",
                f"counterparty argued the window has run; it closes "
                f"{adj.clock.expiry_date}, {adj.clock.days_remaining} days away "
                f"-- argument void",
            )
            # Void the timeliness point WITHOUT discarding any other ground
            # the counterparty raised. Throwing the whole challenge away would
            # silently drop a valid exclusion argument that happened to be
            # bundled with a bad one, and hand the user a claim that had never
            # really been tested.
            adj.challenge = adj.challenge.model_copy(
                update={
                    "defeats_claim": False,
                    "ground": "none" if adj.challenge.ground == "untimely" else adj.challenge.ground,
                    "asserts_window_has_run": False,
                    "argument": (
                        f"[Timeliness argument discarded: the window closes "
                        f"{adj.clock.expiry_date}, {adj.clock.days_remaining} days "
                        f"from now.] Remaining argument: {adj.challenge.argument}"
                    ),
                }
            )
        safe_emit(
            "challenge.result",
            f"{'DEFEATS' if adj.challenge.defeats_claim else 'survives'} "
            f"({adj.challenge.confidence}): {adj.challenge.argument[:120]}",
        )
        safe_emit("rebut", adj.clock.finding.right_summary)
        adj.rebuttal = rebut_challenge(
            adj.clock, adj.challenge, argue_model, source, hooks=[collector]
        )
        safe_emit(
            "rebut.result",
            f"{'holds' if adj.rebuttal.survives else 'conceded'}: "
            f"{adj.rebuttal.answer[:120]}",
        )

    pairs = list(zip(adjudications, sources, strict=True))
    if pairs:
        with ThreadPoolExecutor(max_workers=min(8, len(pairs))) as pool:
            list(pool.map(argue, pairs))

    emit("triage", f"{len(adjudications)} clocks, budget {budget}")
    adjudications = triage(
        adjudications,
        today,
        detect_model,
        budget=budget,
        attention_floor_usd=attention_floor_usd,
        hooks=[collector],
    )

    new_ids: set[str] = set()
    for adj in adjudications:
        entry, is_new = ledger.record(adj, today)
        if is_new:
            new_ids.add(entry.clock_id)
    ledger.save()
    emit("ledger", f"{len(new_ids)} new, {len(adjudications) - len(new_ids)} already known")

    return RunReport(
        today=today,
        provider=f"{provider.name} / {provider.model_id}",
        adjudications=adjudications,
        new_clock_ids=new_ids,
        muted_count=muted_box[0],
        errors=errors,
        metrics=collector.metrics,
    )
