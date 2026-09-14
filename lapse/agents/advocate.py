"""Stage 3 - the advocate.

Sees the claim and the counterparty's argument, and either answers it or
concedes. Where it answers, it drafts the thing that actually has to be sent,
because a deadline without a draft is just anxiety with a date attached.

The advocate is permitted to concede, and this matters: an advocate that
never loses is a rubber stamp, and the adversary stage would be decorative.
"""

from __future__ import annotations

import re

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


_THINKING = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)


def _clean(text: str) -> str:
    """Strip reasoning scaffolding a model may wrap around the letter.

    Some models emit a <thinking> block, or fence the letter in markdown, or
    lead with "Here is the letter:". None of that belongs in something the
    user is one keystroke away from sending.
    """
    text = _THINKING.sub("", text)
    text = re.sub(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$", "", text.strip())
    text = re.sub(r"^\s*(here('s| is) the letter[:.]?|draft[:.]?)\s*", "", text, flags=re.I)
    text = re.sub(r"^\s*-{3,}\s*", "", text.strip())
    return text.strip()


def rebut_challenge(
    clock: DatedClock,
    challenge: Challenge,
    model,
    source_text: str = "",
    hooks: list | None = None,
) -> Rebuttal:
    """Answer the counterparty's argument, and draft the action if it survives."""
    f = clock.finding
    agent = Agent(
        model=model,
        tools=ARGUMENT_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        callback_handler=None,
        hooks=list(hooks or []),
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
        f"The document the counterparty issued:\n<document>\n{source_text}\n</document>\n\n"
        "Answer it or concede it. If it survives, draft what should be sent.\n\n"
        "Before conceding, search the reference documents for anything that "
        "POSTDATES or OVERRIDES the authority they relied on -- a later policy "
        "bulletin, an amended exhibit, a superseding clause. That is where the "
        "answer usually is.\n"
        "Your draft must be sendable as written: no bracketed placeholders, no "
        "[Your Name], no [state the basis here]. Every fact you need is in the "
        "documents you have been given, so fill it in.",
        structured_output_model=Rebuttal,
    )
    rebuttal = result.structured_output
    if rebuttal is not None and rebuttal.survives and not rebuttal.drafted_action.strip():
        # A surviving claim with no draft is the failure this system exists to
        # prevent: a deadline with no way to act on it is just anxiety with a
        # date attached. Ask again, for the draft alone.
        drafter = Agent(
            model=model,
            tools=ARGUMENT_TOOLS,
            system_prompt=(
                "You write the letter that gets sent. Output ONLY the letter "
                "body -- no commentary, no preamble. It must be sendable as "
                "written: no bracketed placeholders of any kind. Use the "
                "specific claim numbers, dates, amounts and authorities you "
                "are given."
            ),
            callback_handler=None,
            hooks=list(hooks or []),
        )
        drafted = str(
            drafter(
                f"Write the letter for this claim.\n\n"
                f"Claim: {f.right_summary}\n"
                f"To: {f.counterparty}\n"
                f"Deadline: {clock.expiry_date}\n"
                f"Authority: {f.authority}\n"
                f"The counterparty's position: {challenge.argument}\n"
                f"Why it fails: {rebuttal.answer}\n"
                f"Evidence relied on: {rebuttal.authority}\n\n"
                f"The document they issued:\n<document>\n{source_text}\n</document>"
            )
        ).strip()
        rebuttal = rebuttal.model_copy(update={"drafted_action": _clean(drafted)})
    return rebuttal or Rebuttal(
        survives=False,
        answer="The advocate produced no answer; treating the claim as unresolved.",
        authority="",
    )
