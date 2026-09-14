"""Stage 1 - the detector.

Reads one incoming document and asks a single question: did this silently
open a window during which the recipient can do something they will lose the
ability to do later?

This is the stage that needs a language model. No incoming document says the
word "appeal", and no client email says the word "scope". Recognising that a
sentence started a clock is the judgment being made here.
"""

from __future__ import annotations

from strands import Agent

from lapse.corpus import Document
from lapse.models import ClockFindings
from lapse.tools import DETECTION_TOOLS

SYSTEM_PROMPT = """\
You find expiring rights hidden in ordinary documents.

A CLOCK is: a right the recipient currently holds, which expires on a date,
where some counterparty benefits if the recipient does nothing. Denials that
can be appealed, requests that can be objected to, goods that can be
returned, notices that can be claimed against, prices that can be matched.

A clock is NOT: a bill, an invoice, a payment due date, a subscription
renewal, an appointment, or any obligation the recipient owes to someone
else. Those chase you. Clocks do not -- that is the entire point. If the
consequence of ignoring the document is that someone pursues you, it is not
a clock.

METHOD, in order:
1. Call list_clock_types to see what kinds of clocks exist.
2. Read the document and decide which kind, if any, it opened. Documents
   almost never name the mechanism, so reason from what the counterparty is
   doing, not from vocabulary.
3. Identify the trigger date -- the date the window opened -- and quote the
   exact text that establishes it. If the document gives no date, say so
   rather than inferring one.
4. Find the window length. If lookup_clock_type says the window is
   INSTRUMENT-DEFINED, you MUST call list_reference_documents and read the
   governing instrument to find the clause that sets it, then cite that
   clause. Never supply a typical or assumed window length. A confidently
   wrong deadline is worse than no deadline: it produces calm inaction until
   the right is gone.
5. Call compute_window_expiry to check the arithmetic. Never compute a date
   yourself.
6. Estimate what acting is worth in dollars where the document supports a
   figure, and state the basis. If it is not quantifiable, say why.

Return every clock you find. Return none, with a reason, if the document
opened no window. Do not invent clocks to be helpful; a false positive here
costs the user their trust in every future silence.
"""


def detect_clocks(document: Document, today: str, model) -> ClockFindings:
    """Find every expiring right in one document."""
    agent = Agent(
        model=model,
        tools=DETECTION_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        callback_handler=None,
    )
    result = agent(
        f"Today is {today}.\n\n"
        f"Examine this document (id: {document.doc_id}) and identify every "
        f"clock it opened.\n\n"
        f"<document id=\"{document.doc_id}\">\n{document.text}\n</document>",
        structured_output_model=ClockFindings,
    )
    return result.structured_output or ClockFindings(
        no_clock_reason="detector returned no structured output"
    )
