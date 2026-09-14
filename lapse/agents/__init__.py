"""The four agents of the Lapse pipeline.

Each stage constructs a FRESH Agent with its own system prompt and its own
empty conversation. Nothing is shared between stages except the typed object
handed forward. That isolation is structural, not requested: an adversary
that can see the advocate's reasoning converges on it, and two agents that
agree because they read the same context have told you nothing.
"""

from lapse.agents.detector import detect_clocks
from lapse.agents.adversary import challenge_clock
from lapse.agents.advocate import rebut_challenge
from lapse.agents.triage import triage

__all__ = ["detect_clocks", "challenge_clock", "rebut_challenge", "triage"]
