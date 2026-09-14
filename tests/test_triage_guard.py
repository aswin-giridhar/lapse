"""The deterministic escalation guard at the end of `triage()`.

The model decides what deserves attention; it is not permitted to let a
valuable right lapse this week. These tests replace the model entirely with a
fake Agent so nothing here makes a network or model call.
"""

from __future__ import annotations

import pytest

import importlib

# NOTE: `lapse.agents.__init__` re-exports a *function* named `triage`, which
# shadows the submodule attribute. Fetch the module explicitly.
triage_mod = importlib.import_module("lapse.agents.triage")
from lapse.agents.triage import triage
from lapse.models import ClockStatus, Decision, Disposition

from tests.factories import make_adjudication

TODAY = "2026-09-14"
FLOOR = 100.0


class _FakeResult:
    def __init__(self, decision):
        self.structured_output = decision


class FakeAgent:
    """Stands in for strands.Agent. Records construction *and* invocation.

    Construction is recorded separately because `Agent(...)` is built after
    triage's early return -- a fake that only counted __call__ could not tell
    "no model was used" from "a model was built but never asked".
    """

    constructions = 0
    calls = 0
    prompts: list[str] = []
    next_decision = Decision(disposition=Disposition.WITHHELD, reason="model withheld")

    def __init__(self, *args, **kwargs):
        type(self).constructions += 1
        self.kwargs = kwargs

    def __call__(self, prompt, **kwargs):
        type(self).calls += 1
        type(self).prompts.append(prompt)
        return _FakeResult(type(self).next_decision)

    @classmethod
    def reset(cls, decision=None):
        cls.constructions = 0
        cls.calls = 0
        cls.prompts = []
        cls.next_decision = decision or Decision(
            disposition=Disposition.WITHHELD, reason="model withheld"
        )


@pytest.fixture
def fake_agent(monkeypatch):
    FakeAgent.reset()
    monkeypatch.setattr(triage_mod, "Agent", FakeAgent)
    return FakeAgent


# --------------------------------------------------------------------------
# The guard: a valuable right about to lapse is surfaced over the model's head
# --------------------------------------------------------------------------


def test_valuable_claim_with_three_days_left_is_escalated_despite_withholding(fake_agent):
    adj = make_adjudication(days_remaining=2, value_usd=4200.0)
    (out,) = triage([adj], TODAY, model=None, attention_floor_usd=FLOOR)

    assert fake_agent.calls == 1, "the model must actually have been consulted first"
    assert out.decision is not None
    assert out.decision.disposition is Disposition.SURFACED
    assert "Escalated by policy" in out.decision.reason
    assert "4,200" in out.decision.reason
    assert "2 days remain" in out.decision.reason


def test_guard_boundary_three_days_escalates(fake_agent):
    (out,) = triage(
        [make_adjudication(days_remaining=3, value_usd=500.0)],
        TODAY,
        model=None,
        attention_floor_usd=FLOOR,
    )
    assert out.decision.disposition is Disposition.SURFACED


def test_guard_boundary_four_days_does_not_escalate(fake_agent):
    (out,) = triage(
        [make_adjudication(days_remaining=4, value_usd=500.0)],
        TODAY,
        model=None,
        attention_floor_usd=FLOOR,
    )
    assert out.decision.disposition is Disposition.WITHHELD


def test_guard_boundary_value_exactly_at_the_floor_escalates(fake_agent):
    (out,) = triage(
        [make_adjudication(days_remaining=1, value_usd=FLOOR)],
        TODAY,
        model=None,
        attention_floor_usd=FLOOR,
    )
    assert out.decision.disposition is Disposition.SURFACED


def test_low_value_claim_with_days_left_is_not_escalated(fake_agent):
    (out,) = triage(
        [make_adjudication(days_remaining=1, value_usd=12.0)],
        TODAY,
        model=None,
        attention_floor_usd=FLOOR,
    )
    assert out.decision.disposition is Disposition.WITHHELD
    assert out.decision.reason == "model withheld"


def test_unquantified_value_escalates_on_imminence_alone(fake_agent):
    """An unquantified claim is unknown, not worthless.

    It used to be compared against the attention floor as though it were worth
    zero, so a right nobody had put a number on could expire unmentioned.
    """
    (out,) = triage(
        [make_adjudication(days_remaining=0, value_usd=None)],
        TODAY,
        model=None,
        attention_floor_usd=FLOOR,
    )
    assert out.decision.disposition is Disposition.SURFACED
    assert "value unstated" in out.decision.reason


def test_guard_leaves_an_already_surfaced_decision_alone(fake_agent):
    FakeAgent.next_decision = Decision(
        disposition=Disposition.SURFACED, reason="the model's own reason"
    )
    (out,) = triage(
        [make_adjudication(days_remaining=1, value_usd=9999.0)],
        TODAY,
        model=None,
        attention_floor_usd=FLOOR,
    )
    assert out.decision.disposition is Disposition.SURFACED
    assert out.decision.reason == "the model's own reason"


def test_a_null_structured_output_falls_back_to_withheld(fake_agent, monkeypatch):
    monkeypatch.setattr(FakeAgent, "next_decision", None)
    (out,) = triage(
        [make_adjudication(days_remaining=20, value_usd=50.0)],
        TODAY,
        model=None,
        attention_floor_usd=FLOOR,
    )
    assert out.decision.disposition is Disposition.WITHHELD
    assert out.decision.reason == "triage produced no decision"


# --------------------------------------------------------------------------
# Dispositions decided without any model call at all
# --------------------------------------------------------------------------


def test_lapsed_clocks_are_dispositioned_without_a_model_call(fake_agent):
    adj = make_adjudication(
        days_remaining=-14,
        value_usd=5000.0,
        status=ClockStatus.LAPSED,
        expiry_date="2026-08-31",
    )
    (out,) = triage([adj], TODAY, model=None, attention_floor_usd=FLOOR)

    assert out.decision.disposition is Disposition.LAPSED
    assert "2026-08-31" in out.decision.reason
    assert "14 days ago" in out.decision.reason
    assert fake_agent.calls == 0
    assert fake_agent.constructions == 0, "no Agent should even be constructed"


def test_defeated_clocks_are_dispositioned_without_a_model_call(fake_agent):
    adj = make_adjudication(days_remaining=5, value_usd=5000.0, survives=False)
    (out,) = triage([adj], TODAY, model=None, attention_floor_usd=FLOOR)

    assert out.decision.disposition is Disposition.DEFEATED
    assert out.decision.reason == adj.rebuttal.answer
    assert fake_agent.calls == 0
    assert fake_agent.constructions == 0


def test_a_lapsed_clock_is_never_escalated_by_the_guard(fake_agent):
    """A lapsed, valuable clock is a fact, not an interruption."""
    adj = make_adjudication(
        days_remaining=-1,
        value_usd=1_000_000.0,
        status=ClockStatus.LAPSED,
        expiry_date="2026-09-13",
    )
    (out,) = triage([adj], TODAY, model=None, attention_floor_usd=FLOOR)
    assert out.decision.disposition is Disposition.LAPSED


# --------------------------------------------------------------------------
# Mixed dockets
# --------------------------------------------------------------------------


def test_only_live_surviving_claims_reach_the_model(fake_agent):
    docket = [
        make_adjudication(days_remaining=-3, value_usd=900.0, status=ClockStatus.LAPSED),
        make_adjudication(days_remaining=5, value_usd=900.0, survives=False),
        make_adjudication(days_remaining=20, value_usd=900.0, summary="the live one"),
    ]
    out = triage(docket, TODAY, model=None, attention_floor_usd=FLOOR)

    assert [a.decision.disposition for a in out] == [
        Disposition.LAPSED,
        Disposition.DEFEATED,
        Disposition.WITHHELD,
    ]
    assert fake_agent.calls == 1
    assert "the live one" in fake_agent.prompts[0]


def test_every_adjudication_is_returned_and_mutated_in_place(fake_agent):
    docket = [
        make_adjudication(days_remaining=2, value_usd=900.0),
        make_adjudication(days_remaining=30, value_usd=10.0),
    ]
    out = triage(docket, TODAY, model=None, attention_floor_usd=FLOOR)
    assert out is docket
    assert all(a.decision is not None for a in out)


def test_a_claim_without_a_rebuttal_is_recorded_not_lost(fake_agent):
    """An un-argued live clock must still leave triage with a disposition.

    Previously it entered no bucket and vanished from the report entirely --
    the exact failure this system exists to prevent, reproduced inside it.
    """
    adj = make_adjudication(days_remaining=1, value_usd=9999.0, with_rebuttal=False)
    (out,) = triage([adj], TODAY, model=None, attention_floor_usd=FLOOR)
    assert out.decision is not None
    assert out.decision.disposition is Disposition.WITHHELD
    assert out.decision.revisit_on == out.clock.expiry_date
    assert fake_agent.constructions == 0
