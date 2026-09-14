"""Run telemetry.

Strands already collects per-invocation token counts and tool-use records and
then throws them away. This makes them visible, which matters twice over: a
user deciding whether to trust a silence should be able to see that the agent
actually looked, and the cost of a run should be a measured number rather than
an estimate.

One trap, learned the hard way during development: `accumulated_usage` on an
agent's metrics is **cumulative for that agent**, not per invocation. Summing
it across invocations double-counts every agent called more than once. This
collector records deltas per agent instead, and holds a strong reference to
each agent so its id() cannot be recycled by the garbage collector onto a
different object -- a failure that produced a completely plausible, and
completely wrong, token count.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import AfterInvocationEvent

# Amazon Nova Pro, us-west-2, USD per million tokens.
PRICE_PER_MTOK_IN = 0.80
PRICE_PER_MTOK_OUT = 3.20


@dataclass
class RunMetrics:
    input_tokens: int = 0
    output_tokens: int = 0
    invocations: int = 0
    agents: int = 0
    tool_calls: dict[str, int] = field(default_factory=dict)

    @property
    def estimated_cost_usd(self) -> float:
        return (
            self.input_tokens * PRICE_PER_MTOK_IN / 1e6
            + self.output_tokens * PRICE_PER_MTOK_OUT / 1e6
        )

    def summary(self) -> str:
        tools = ", ".join(
            f"{name}×{n}" for name, n in sorted(self.tool_calls.items(), key=lambda kv: -kv[1])
        )
        return (
            f"{self.invocations} model invocations across {self.agents} isolated agents  ·  "
            f"{self.input_tokens:,} in / {self.output_tokens:,} out tokens  ·  "
            f"${self.estimated_cost_usd:.3f}"
            + (f"\n  tools called: {tools}" if tools else "")
        )


class MetricsCollector(HookProvider):
    """Accumulates token usage and tool calls across every agent in a run."""

    def __init__(self) -> None:
        self.metrics = RunMetrics()
        self._seen: dict[int, tuple[int, int]] = {}
        self._keepalive: list[object] = []  # prevents id() reuse after GC
        self._lock = Lock()

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(AfterInvocationEvent, self._on_done)

    def _on_done(self, event) -> None:
        agent = event.agent
        elm = agent.event_loop_metrics
        usage = elm.accumulated_usage or {}
        current = (usage.get("inputTokens", 0), usage.get("outputTokens", 0))
        with self._lock:
            self._keepalive.append(agent)
            previous = self._seen.get(id(agent), (0, 0))
            self.metrics.input_tokens += current[0] - previous[0]
            self.metrics.output_tokens += current[1] - previous[1]
            self._seen[id(agent)] = current
            self.metrics.invocations += 1
            self.metrics.agents = len(self._seen)
            for name in _tool_names(elm):
                self.metrics.tool_calls[name] = self.metrics.tool_calls.get(name, 0) + 1


def _tool_names(event_loop_metrics) -> list[str]:
    """Best-effort extraction of tool names used, tolerant of SDK shape changes."""
    names: list[str] = []
    usage = getattr(event_loop_metrics, "tool_metrics", None) or {}
    try:
        for key, tm in usage.items():
            calls = getattr(tm, "call_count", 0) or 0
            names.extend([key] * max(0, calls))
    except AttributeError:
        return []
    return names
