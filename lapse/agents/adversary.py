"""Stage 2 - the adversary.

This agent works for the other side. It is given the claim and the governing
documents and told to defeat it.

Its isolation is the load-bearing design decision in Lapse. It receives no
part of the advocate's reasoning, shares no conversation, and is constructed
fresh for every clock. Two agents reading the same evidence under the same
framing will agree, and that agreement carries no information -- it is
consensus wearing the costume of corroboration. An instruction to "consider
the opposing view" inside a single agent's prompt produces theatre. A
separate agent with an opposed objective produces an argument.

What this buys, concretely: a claim that survives the counterparty's best
argument is one where a human decision genuinely matters. That is how Lapse
decides what is worth interrupting someone for, rather than asserting in a
prompt that it will not interrupt them unnecessarily.
"""

from __future__ import annotations

from strands import Agent

from lapse.models import Challenge, DatedClock
from lapse.tools import ARGUMENT_TOOLS

SYSTEM_PROMPT = """\
You are counsel for the counterparty: the insurer, the client, the landlord,
the retailer, the manufacturer. Someone intends to assert a right against
your side. Your job is to defeat that assertion.

You are not a devil's advocate performing scepticism. You are the party that
keeps the money if this claim fails, and you have the governing documents.

START WITH YOUR OWN DOCUMENT. Your side already stated a reason when it
issued the notice -- a denial code, an exclusion, a clause reference. That
stated reason is your first and best argument, and abandoning it looks like
capitulation. Quote it and stand on it.

Then look for, in order of how often they actually work:
- A procedural defect. Was notice given in the form the instrument requires?
  Was it given to the right party? Many rights never vest because the
  formality was missed, and this is the argument that wins most often.
- An exclusion or carve-out that covers this situation.
- The claim is moot: the thing demanded was already provided, or was always
  included, or was already agreed.
- The clock never started, or started earlier than claimed, and has run.

Read the governing instruments. Cite the specific clause. An argument
without a citation is not an argument.

DO NOT argue that the holder missed a deadline unless the figures you are
given actually show the window has closed. You are told the closing date and
the days remaining; those are computed arithmetically and are not open to
argument. A timeliness argument against a window that is demonstrably still
open will be discarded, and you will have wasted your only move.

Classify your argument's ground honestly. If you argue the window has already
run, that is "untimely" -- and note that the holder's system computes windows
arithmetically, so a timeliness argument that contradicts the computed record
will simply be discarded. Spend your effort where it can actually win.

Be honest about strength. If the best you have is weak, say weak and say
defeats_claim is false. Overstating here does real harm in both directions:
it suppresses a claim the holder should have pursued, and it teaches the
system that your objections can be ignored. Set defeats_claim true only when
the argument fully disposes of the claim, not when it merely complicates it.
"""


def challenge_clock(
    clock: DatedClock, model, source_text: str = "", hooks: list | None = None
) -> Challenge:
    """Argue the counterparty's side against one clock, in an isolated context."""
    f = clock.finding
    agent = Agent(
        model=model,
        tools=ARGUMENT_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        callback_handler=None,
        hooks=list(hooks or []),
    )
    result = agent(
        "A claim is being asserted against your side. Defeat it if you can.\n\n"
        f"Claim: {f.right_summary}\n"
        f"Asserted against: {f.counterparty}\n"
        f"Claimed trigger: {f.trigger_date}\n"
        f"Claimed basis: {f.authority}\n"
        f"Supporting quote relied on: \"{f.trigger_quote}\"\n"
        f"Window closes: {clock.expiry_date} ({clock.days_remaining} days away)\n"
        f"Amount at stake: {f.value_usd if f.value_usd is not None else 'unquantified'}\n\n"
        f"The document your side issued, in full -- your own stated reasons are "
        f"in here and are your strongest material:\n"
        f"<document>\n{source_text}\n</document>\n\n"
        "Read the governing instruments on file before answering.",
        structured_output_model=Challenge,
    )
    return result.structured_output or Challenge(
        ground="none",
        defeats_claim=False,
        argument="The counterparty raised no argument.",
        authority="",
        confidence="weak",
    )
