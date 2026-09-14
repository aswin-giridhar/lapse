"""Tools the agents call.

Everything in here is ordinary deterministic Python. The division of labour
is deliberate and is the core correctness claim of this system:

    the model decides WHICH clock applies and WHAT it means
    these tools decide WHEN it closes and WHAT the documents actually say

No date in a Lapse output is ever produced by token generation.
"""

from __future__ import annotations

import re

from strands import tool

from lapse import clocks
from lapse.corpus import reference_index
from lapse.dates import compute_expiry, days_remaining, parse_date


@tool
def compute_window_expiry(
    trigger_date: str, window_days: int, business_days: bool, today: str
) -> str:
    """Compute when a window closes, and how long is left. Use this for EVERY date.

    Args:
        trigger_date: ISO date (YYYY-MM-DD) on which the window opened.
        window_days: Length of the window in days.
        business_days: True to count business days only (weekends and US
            federal holidays excluded), False for calendar days.
        today: ISO date (YYYY-MM-DD) to measure remaining time against.

    Returns:
        A description of the expiry date, days remaining, and whether the
        window is still live or has already lapsed.
    """
    expiry = compute_expiry(parse_date(trigger_date), window_days, business_days)
    left = days_remaining(expiry, parse_date(today))
    basis = "business" if business_days else "calendar"
    state = (
        f"LIVE, {left} days remaining"
        if left >= 0
        else f"LAPSED {abs(left)} days ago"
    )
    return (
        f"A {window_days} {basis}-day window opened on {trigger_date} closes on "
        f"{expiry.isoformat()}. As of {today} it is {state}."
    )


@tool
def list_clock_types() -> str:
    """List every kind of expiring right Lapse knows about, with its window and authority.

    Returns:
        The clock registry, including which windows are fixed by statute and
        which are defined by the governing instrument and must be read.
    """
    return clocks.catalogue()


@tool
def lookup_clock_type(key: str) -> str:
    """Look up one clock type by its registry key.

    Args:
        key: Registry key, e.g. "insurance_internal_appeal".

    Returns:
        The window length, counterparty, governing authority and cautions, or
        a message listing valid keys if the key is unknown.
    """
    ct = clocks.lookup(key)
    if ct is None:
        return (
            f"No clock type '{key}'. Valid keys: {', '.join(sorted(clocks.REGISTRY))}"
        )
    window = (
        f"{ct.default_window} {'business' if ct.business_days else 'calendar'} days"
        if ct.default_window is not None
        else (
            "INSTRUMENT-DEFINED. There is no safe default. Read the governing "
            "document and quote the clause that sets the window."
            + (
                " Windows of this kind are counted in BUSINESS days; set "
                "business_days=true."
                if ct.business_days
                else ""
            )
        )
    )
    return (
        f"{ct.key}: {ct.label}\ncounterparty: {ct.counterparty_role}\n"
        f"window: {window}\nauthority: {ct.authority}\n"
        f"jurisdiction dependent: {ct.jurisdiction_dependent}\nnotes: {ct.notes}"
    )


@tool
def list_reference_documents() -> str:
    """List the governing instruments on file (plans, leases, contracts, policy bulletins).

    Returns:
        Each reference document's id and opening lines.
    """
    docs = reference_index()
    if not docs:
        return "No reference documents on file."
    return "\n".join(
        f"- {d.doc_id}: {d.text.strip().splitlines()[0][:100]}" for d in docs.values()
    )


@tool
def read_reference_document(doc_id: str) -> str:
    """Read a governing instrument in full.

    Args:
        doc_id: Filename from list_reference_documents, e.g. "meridian_sow.md".

    Returns:
        The full text, or a message listing valid ids.
    """
    docs = reference_index()
    if doc_id not in docs:
        return f"No such document '{doc_id}'. On file: {', '.join(sorted(docs))}"
    return docs[doc_id].text


@tool
def search_reference_documents(query: str) -> str:
    """Search the governing instruments for a term and return surrounding context.

    Use this to find the clause that sets a window, or evidence that answers a
    counterparty's argument.

    Args:
        query: A word or phrase, e.g. "business days" or "investigational".

    Returns:
        Matching passages with their document id, or a message if nothing matched.
    """
    needle = query.strip().lower()
    if not needle:
        return "Empty query."
    hits: list[str] = []
    for doc in reference_index().values():
        # Up to three excerpts per document. Returning only the first was a
        # false economy: the clause that actually governs is routinely the
        # second or third mention, the first being a heading or a cross
        # reference.
        for n, match in enumerate(re.finditer(re.escape(needle), doc.text.lower())):
            if n >= 3:
                break
            start = max(0, match.start() - 300)
            end = min(len(doc.text), match.end() + 300)
            hits.append(f"--- {doc.doc_id} ---\n...{doc.text[start:end].strip()}...")
    if not hits:
        return f"No reference document contains '{query}'."
    return "\n\n".join(hits)


DETECTION_TOOLS = [
    compute_window_expiry,
    list_clock_types,
    lookup_clock_type,
    list_reference_documents,
    read_reference_document,
    search_reference_documents,
]

ARGUMENT_TOOLS = [
    compute_window_expiry,
    list_reference_documents,
    read_reference_document,
    search_reference_documents,
]
