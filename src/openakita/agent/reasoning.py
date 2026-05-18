"""V2 reasoning engine surface — canonical home for ``ReasoningEngine``.

Per ADR-0001 (fork-style rewrite), ADR-0003 (agent/ packaging), and
the Phase 2 sub-commit plan (commit 17), the canonical import path
for the ReAct loop (Reason → Act → Observe) moves to
:mod:`openakita.agent.reasoning`. The v2 plan calls for the if/else
cascade inside the legacy engine to eventually be replaced by a
``runtime.state_graph.StateGraph``-driven dispatcher.

Current shape
-------------
:class:`ReasoningEngine`, :class:`Decision`, :class:`DecisionType`,
and :class:`Checkpoint` are re-exported from ``core.reasoning_engine``.
The 7,987 LOC body holds the giant Decision-cascade plus 30+ helper
functions for source-tag consistency, unbacked-action-claim guards,
loop detection, tool-failure acknowledgement, etc.

Why we ship a thin facade now:

* The deep refactor is to invert control so the engine becomes a
  pluggable node table consumed by ``runtime.state_graph``. That
  requires plumbing 30+ helpers into ``runtime/state_graph/nodes/``
  and rewriting their tests against the new node API — a multi-day
  surgery whose blast radius covers ``core.agent``,
  ``agents.orchestrator``, the SSE replay layer, and the prompt
  builder. The plan stages this under Phase 8 once ``core/`` is
  removed in one sweep.
* Keeping the facade here lets the new ``agent/`` import surface
  stabilise and gives parity tests a stable entry point.

Migration guidance
------------------
* New code: ``from openakita.agent.reasoning import ReasoningEngine``
* Legacy callers in ``core.agent`` continue to work unchanged.
"""

from __future__ import annotations

from openakita.core.reasoning_engine import (
    Checkpoint,
    Decision,
    DecisionType,
    ReasoningEngine,
)

__all__ = [
    "Checkpoint",
    "Decision",
    "DecisionType",
    "ReasoningEngine",
]
