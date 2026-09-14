"""Stage 4 - triage.

Everything reaching this stage is real and has survived the counterparty.
That is still not sufficient reason to interrupt someone.

Triage is comparative on purpose: it sees the whole surviving set at once and
spends a strict interruption budget across it. A per-item "is this important?"
question has no way to answer "yes, but less than that other one", which is
exactly the judgment that separates an agent from a notification system.
"""

from __future__ import annotations

from strands import Agent

from lapse.models import Adjudication, Decision, Disposition

SYSTEM_PROMPT = """\
You decide what is worth interrupting a person for. Default to silence.

You are given every claim that is real and has survived the counterparty's
best argument. You may surface at most the number of items in the stated
interruption budget, and you should usually surface fewer.

Surface an item only when ALL of these hold:
- Acting requires a decision only the person can make, or an approval only
  they can give.
- The value at stake exceeds the cost of the interruption itself. Their
  attention has a price. A claim worth less than a few minutes of it should
  be handled silently or not at all, however easy it would be to mention.
  A claim marked "unquantified" is NOT a claim worth nothing -- it is one
  whose value was not stated. Judge it on consequence instead, and never
  withhold it merely for lacking a number.
- The timing is right NOW. A real claim with three months of runway is not
  urgent; withhold it and set revisit_on so it returns when it matters.

Withhold everything else, and give the actual reason. "Not urgent yet" and
"below the value of your attention" and "no decision required" are different
reasons, and the person should be able to see which applied.

You are not ranking by urgency. A claim expiring in two days may be worth
less than one expiring in two weeks. Reason about consequence, not proximity.
"""


def triage(
    adjudications: list[Adjudication],
    today: str,
    model,
    budget: int = 1,
    attention_floor_usd: float = 100.0,
    hooks: list | None = None,
) -> list[Adjudication]:
    """Decide which surviving claims reach the human.

    A deterministic guard runs after the model: any surviving claim above the
    attention floor with three days or fewer remaining is surfaced regardless
    of what triage concluded. The model is deciding what is worth attention;
    it is not permitted to let a valuable right lapse this week.
    """
    live = [
        a
        for a in adjudications
        if a.rebuttal is not None
        and a.rebuttal.survives
        and a.clock.status.value == "live"
    ]

    for a in adjudications:
        if a.clock.status.value == "lapsed":
            a.decision = Decision(
                disposition=Disposition.LAPSED,
                reason=(
                    f"The window closed on {a.clock.expiry_date}, "
                    f"{abs(a.clock.days_remaining)} days ago."
                ),
            )
        elif a.rebuttal is not None and not a.rebuttal.survives:
            a.decision = Decision(
                disposition=Disposition.DEFEATED,
                reason=a.rebuttal.answer,
            )

    if not live:
        return _decide_the_undecided(adjudications)

    docket = "\n\n".join(
        f"[{i}] {a.clock.finding.right_summary}\n"
        f"    against: {a.clock.finding.counterparty}\n"
        f"    closes: {a.clock.expiry_date} ({a.clock.days_remaining} days)\n"
        f"    value: {a.clock.finding.value_usd if a.clock.finding.value_usd is not None else 'unquantified'}"
        f" ({a.clock.finding.value_basis})\n"
        f"    survived the counterparty because: {a.rebuttal.answer[:300]}"
        for i, a in enumerate(live)
    )

    for i, a in enumerate(live):
        # A fresh agent per item. Reusing one accumulates the conversation, so
        # item [1] would see item [0]'s decision and anchor on it -- which
        # would quietly contradict the isolation this design claims, and cost
        # O(n^2) tokens for the privilege.
        agent = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            callback_handler=None,
            hooks=list(hooks or []),
        )
        result = agent(
            f"Today is {today}. Interruption budget: {budget} item(s) total.\n"
            f"Attention floor: claims worth less than ${attention_floor_usd:.0f} "
            f"are generally not worth an interruption.\n\n"
            f"The full docket of surviving claims:\n\n{docket}\n\n"
            f"Decide the disposition of item [{i}] only, judged against the "
            f"whole docket above.",
            structured_output_model=Decision,
        )
        a.decision = result.structured_output or Decision(
            disposition=Disposition.WITHHELD, reason="triage produced no decision"
        )

    # Enforce the interruption budget. Stating it in the prompt is a request;
    # this makes it an invariant. Where the model surfaced more than the budget
    # allows, keep the most valuable and withhold the rest with a reason that
    # says so honestly.
    surfaced = [a for a in live if a.decision and a.decision.disposition is Disposition.SURFACED]
    if len(surfaced) > budget:
        surfaced.sort(key=lambda a: (a.clock.finding.value_usd or 0.0), reverse=True)
        for a in surfaced[budget:]:
            a.decision = Decision(
                disposition=Disposition.WITHHELD,
                reason=(
                    f"Real and surviving, but outside today's interruption "
                    f"budget of {budget}."
                ),
                revisit_on=a.clock.expiry_date,
            )

    # Deterministic guard on the join. The model decides what deserves
    # attention; it does not get to let a valuable right expire this week.
    for a in live:
        value = a.clock.finding.value_usd
        # An unquantified claim is unknown, not worthless. It escalates on
        # imminence alone, because the alternative is that a right nobody put
        # a number on expires unmentioned.
        qualifies = value is None or value >= attention_floor_usd
        if (
            a.clock.days_remaining <= 3
            and qualifies
            and a.decision is not None
            and a.decision.disposition is not Disposition.SURFACED
        ):
            a.decision = Decision(
                disposition=Disposition.SURFACED,
                reason=(
                    f"Escalated by policy: "
                    f"{f'${value:,.0f} at stake' if value is not None else 'value unstated'}"
                    f" and only {a.clock.days_remaining} days remain."
                ),
            )
    return _decide_the_undecided(adjudications)


def _decide_the_undecided(adjudications: list[Adjudication]) -> list[Adjudication]:
    """No clock may leave triage without a disposition.

    An adjudication with `decision is None` falls out of every bucket in the
    report and vanishes without trace -- which is precisely the failure this
    whole system exists to prevent, reproduced inside it. Called at every exit
    from triage, not just the last one.
    """
    for a in adjudications:
        if a.decision is None:
            a.decision = Decision(
                disposition=Disposition.WITHHELD,
                reason=(
                    "No disposition was reached for this clock; withheld so it "
                    "is recorded rather than lost."
                ),
                revisit_on=a.clock.expiry_date,
            )
    return adjudications
