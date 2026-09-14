"""The clock registry: what kinds of expiring rights exist, and how long they run.

This is the honest centre of Lapse's domain knowledge, and its honest limit.

Two kinds of entry live here:

  STATUTORY / REGULATORY -- the window is set by law and the same for everyone
  in the jurisdiction. `default_window` is authoritative.

  INSTRUMENT-DEFINED -- the window is set by the contract, plan or offer in
  front of you, and varies by document. `default_window` is None and the agent
  MUST read the governing instrument to find it. Guessing a typical value here
  would be the single most dangerous thing this system could do, because a
  plausible wrong deadline is worse than no deadline at all: it produces
  confident inaction right up until the right is gone.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ClockType(BaseModel):
    key: str
    label: str
    counterparty_role: str
    default_window: Optional[int]
    business_days: bool = False
    authority: str
    jurisdiction_dependent: bool = False
    notes: str = ""


REGISTRY: dict[str, ClockType] = {
    ct.key: ct
    for ct in [
        ClockType(
            key="insurance_internal_appeal",
            label="Internal appeal of an adverse benefit determination",
            counterparty_role="Health plan / insurer",
            default_window=180,
            authority="ERISA 29 CFR 2560.503-1(h)(3); plan Certificate of Coverage",
            notes=(
                "180 days is the ERISA floor for group health plans. Non-ERISA "
                "plans and short-term policies may differ; always confirm against "
                "the plan document."
            ),
        ),
        ClockType(
            key="contract_scope_objection",
            label="Notice that requested work falls outside the agreed scope",
            counterparty_role="Client",
            default_window=None,
            business_days=True,
            authority="The executed statement of work",
            notes=(
                "Entirely instrument-defined. Read the change-control clause. "
                "Many SOWs deem unobjected work included in the fixed fee."
            ),
        ),
        ClockType(
            key="habitability_repair_notice",
            label="Landlord's period to commence repair after written notice",
            counterparty_role="Landlord",
            default_window=14,
            jurisdiction_dependent=True,
            authority="State landlord-tenant statute; lease repair clause",
            notes=(
                "Varies materially by state (often 7-30 days) and the clock "
                "usually starts only on notice given in the form the lease "
                "requires. Verify both before relying on this."
            ),
        ),
        ClockType(
            key="product_recall_free_remedy",
            label="Free repair, replacement or refund under a safety recall",
            counterparty_role="Manufacturer",
            default_window=None,
            authority="The recall notice itself",
            notes="Recall remedy periods are set by the notice, not by statute.",
        ),
        ClockType(
            key="price_protection",
            label="Refund of the difference after a post-purchase price drop",
            counterparty_role="Retailer",
            default_window=None,
            authority="Retailer price-protection policy",
        ),
        ClockType(
            key="mail_in_rebate",
            label="Mail-in rebate submission",
            counterparty_role="Manufacturer / rebate processor",
            default_window=None,
            authority="The rebate offer terms",
            notes="Usually an absolute postmark date rather than a rolling window.",
        ),
        ClockType(
            key="card_chargeback",
            label="Payment card dispute",
            counterparty_role="Merchant",
            default_window=60,
            authority="Fair Credit Billing Act, 15 U.S.C. 1666; network rules",
            notes="60 days from the statement on which the charge appeared.",
        ),
        ClockType(
            key="retail_return",
            label="Return of goods for refund or exchange",
            counterparty_role="Retailer",
            default_window=None,
            authority="Retailer return policy",
        ),
        ClockType(
            key="warranty_claim",
            label="Claim under a manufacturer or extended warranty",
            counterparty_role="Manufacturer / warranty administrator",
            default_window=None,
            authority="The warranty instrument",
        ),
        ClockType(
            key="grant_reporting_obligation",
            label="Funder reporting obligation with a clawback consequence",
            counterparty_role="Funder",
            default_window=None,
            authority="The grant agreement",
        ),
    ]
}


def lookup(key: str) -> Optional[ClockType]:
    return REGISTRY.get(key)


def catalogue() -> str:
    """A compact description of the registry, for injection into a prompt."""
    lines = []
    for ct in REGISTRY.values():
        window = (
            f"{ct.default_window} {'business' if ct.business_days else 'calendar'} days"
            if ct.default_window is not None
            else (
                "INSTRUMENT-DEFINED - you must read the governing document"
                + (
                    " (and note this kind of window is counted in BUSINESS days)"
                    if ct.business_days
                    else ""
                )
            )
        )
        lines.append(
            f"- {ct.key}: {ct.label}\n"
            f"    counterparty: {ct.counterparty_role}\n"
            f"    window: {window}\n"
            f"    authority: {ct.authority}"
            + (f"\n    caution: {ct.notes}" if ct.notes else "")
        )
    return "\n".join(lines)
