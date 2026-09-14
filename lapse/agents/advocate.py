"""Stage 3 - the advocate.

Sees the claim and the counterparty's argument, and either answers it or
concedes. Where it answers, it drafts the thing that actually has to be sent,
because a deadline without a draft is just anxiety with a date attached.

The advocate is permitted to concede, and this matters: an advocate that
never loses is a rubber stamp, and the adversary stage would be decorative.
"""

from __future__ import annotations

from strands import Agent

from lapse.models import Challenge, DatedClock, Rebuttal
from lapse.tools import ARGUMENT_TOOLS

SYSTEM_PROMPT = """\
You act for the holder of an expiring right. The counterparty has stated
why they believe the claim fails. Answer it, or concede it.

Concede when the argument is sound. A claim that has genuinely been defeated
should not reach the user, and pretending otherwise wastes the one thing this
system is trying to protect -- their attention, and their willingness to
believe you when you do speak.

If the claim survives:
- Say precisely why the counterparty's argument fails, citing the clause,
  bulletin or fact that answers it. Search the reference documents; the
  answer is usually in an instrument that post-dates or overrides the one
  they relied on.
- Draft the actual document to send. A letter, an email, a filing. Make it
  complete enough to send after a read-through: identify the claim, state
  the basis, cite the authority, and say what is being requested. Address
  the counterparty's argument explicitly -- they have already told you what
  they will say, so answering it in advance is free.
- Write in the user's voice: direct, specific, unemotional. No threats, no
  legal theatre, no citations you have not verified in the documents on file.

Never assert a fact that is not in the documents you were given.
"""


def rebut_challenge(clock: DatedClock, challenge: Challenge, model) -> Rebuttal:
    """Answer the counterparty's argument, and draft the action if it survives."""
    f = clock.finding
    agent = Agent(
        model=model,
        tools=ARGUMENT_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        callback_handler=None,
    )
    result = agent(
        f"Your client's claim: {f.right_summary}\n"
        f"Against: {f.counterparty}\n"
        f"Basis: {f.authority}\n"
        f"Deadline to act: {clock.expiry_date} ({clock.days_remaining} days)\n"
        f"At stake: {f.value_usd if f.value_usd is not None else 'unquantified'}\n\n"
        f"The counterparty says:\n"
        f"  \"{challenge.argument}\"\n"
        f"  relying on: {challenge.authority or 'nothing specific'}\n"
        f"  their own assessment of strength: {challenge.confidence}\n\n"
        "Answer it or concede it. If it survives, draft what should be sent.",
        structured_output_model=Rebuttal,
    )
    return result.structured_output or Rebuttal(
        survives=False,
        answer="The advocate produced no answer; treating the claim as unresolved.",
        authority="",
    )
