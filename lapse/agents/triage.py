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
        return adjudications

    docket = "\n\n".join(
        f"[{i}] {a.clock.finding.right_summary}\n"
        f"    against: {a.clock.finding.counterparty}\n"
        f"    closes: {a.clock.expiry_date} ({a.clock.days_remaining} days)\n"
        f"    value: {a.clock.finding.value_usd if a.clock.finding.value_usd is not None else 'unquantified'}"
        f" ({a.clock.finding.value_basis})\n"
        f"    survived the counterparty because: {a.rebuttal.answer[:300]}"
        for i, a in enumerate(live)
    )

    agent = Agent(model=model, system_prompt=SYSTEM_PROMPT, callback_handler=None)
    for i, a in enumerate(live):
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

    # Deterministic guard on the join. The model decides what deserves
    # attention; it does not get to let a valuable right expire this week.
    for a in live:
        value = a.clock.finding.value_usd or 0.0
        if (
            a.clock.days_remaining <= 3
            and value >= attention_floor_usd
            and a.decision is not None
            and a.decision.disposition is not Disposition.SURFACED
        ):
            a.decision = Decision(
                disposition=Disposition.SURFACED,
                reason=(
                    f"Escalated by policy: ${value:,.0f} at stake and only "
                    f"{a.clock.days_remaining} days remain."
                ),
            )
    return adjudications
