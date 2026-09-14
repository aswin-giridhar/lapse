"""Typed payloads passed between the agents.

These are Pydantic models rather than free text on purpose: each agent in the
pipeline hands the next one a structured object, so a hand-off cannot quietly
degrade into prose that the next stage has to re-parse.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ClockStatus(str, Enum):
    LIVE = "live"
    LAPSED = "lapsed"


class Disposition(str, Enum):
    SURFACED = "surfaced"
    DEFEATED = "defeated"          # the counterparty's argument held
    WITHHELD = "withheld"          # real, but not worth an interruption yet
    LAPSED = "lapsed"              # the window already closed


class ClockFinding(BaseModel):
    """A right with an expiry, detected in one document."""

    doc_id: str = Field(description="Filename of the document this was found in")
    clock_kind: str = Field(description="Registry key, e.g. insurance_internal_appeal")
    right_summary: str = Field(
        description="One sentence, in plain language: what the holder is entitled to do"
    )
    counterparty: str = Field(description="Who benefits if this window closes unused")
    trigger_date: str = Field(description="ISO date the window opened (YYYY-MM-DD)")
    trigger_quote: str = Field(
        description="Verbatim quote from the document establishing the trigger date"
    )
    window_days: int = Field(description="Length of the window")
    business_days: bool = Field(default=False, description="Count business days only")
    authority: str = Field(
        description="The instrument or statute that sets this window, cited specifically"
    )
    value_usd: Optional[float] = Field(
        default=None, description="What acting is worth, if quantifiable"
    )
    value_basis: str = Field(
        default="", description="How value_usd was arrived at, or why it is unquantifiable"
    )


class DatedClock(BaseModel):
    """A finding with its expiry computed deterministically."""

    finding: ClockFinding
    expiry_date: str
    days_remaining: int
    status: ClockStatus


class Challenge(BaseModel):
    """The counterparty's best argument that this claim fails.

    Produced by an agent that never sees the advocate's reasoning.
    """

    defeats_claim: bool = Field(
        description="True if this argument fully defeats the claim, not merely weakens it"
    )
    argument: str = Field(description="The counterparty's position, stated in their voice")
    authority: str = Field(
        description="The specific clause, policy or fact relied on. Empty if none exists."
    )
    confidence: Literal["weak", "arguable", "strong"] = Field(
        description="How strongly this argument would hold if tested"
    )


class Rebuttal(BaseModel):
    """The holder's answer to the challenge, or a concession."""

    survives: bool = Field(description="True if the claim survives the challenge")
    answer: str = Field(description="Why the challenge fails, or why it succeeds")
    authority: str = Field(description="The specific evidence relied on to rebut")
    drafted_action: str = Field(
        default="", description="The letter, email or filing to send. Empty if conceded."
    )


class Decision(BaseModel):
    """Whether this reaches the human at all."""

    disposition: Disposition
    reason: str = Field(description="Why this was surfaced or withheld, in one sentence")
    revisit_on: Optional[str] = Field(
        default=None, description="ISO date to reconsider a withheld clock"
    )


class Adjudication(BaseModel):
    """The complete record for one clock, end to end."""

    clock: DatedClock
    challenge: Optional[Challenge] = None
    rebuttal: Optional[Rebuttal] = None
    decision: Optional[Decision] = None


class ClockFindings(BaseModel):
    """Container so a detector pass can return zero or many findings."""

    findings: list[ClockFinding] = Field(default_factory=list)
    no_clock_reason: str = Field(
        default="",
        description="If findings is empty, why this document starts no clock",
    )
