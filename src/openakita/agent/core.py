"""V2 agent surface — canonical home for the top-level ``Agent`` class.

Per ADR-0001 (fork-style rewrite), ADR-0003 (agent/ packaging), and
the Phase 2 sub-commit plan (commit 18), the canonical import path
for the top-level Agent lifecycle (`init` → `run_task` → `shutdown`)
moves to :mod:`openakita.agent.core`. The v2 plan calls for stripping
the legacy 8,400 LOC ``core.agent`` body down to ~500 LOC focused on
the Agent lifecycle plus :meth:`Agent.run_task`, delegating everything
else to :mod:`agent.reasoning`, :mod:`agent.tools`, :mod:`agent.brain`,
and :mod:`agent.context`.

Current shape
-------------
:class:`Agent` plus the primary-agent registry helpers
(:func:`get_primary_agent`, :func:`set_primary_agent`) and the
:class:`PromptStrategy` enum are re-exported from ``core.agent``. The
legacy module also carries 20+ private helpers for desktop notification,
attachment routing, destructive-intent classification, and risk
authorization replay — that surface stays in ``core/`` until Phase 8
removes the legacy package wholesale.

Why this commit is a facade:

* The legacy ``Agent`` is the longest single file in the codebase
  (8,433 LOC). A faithful slim rewrite requires re-homing the
  desktop/attachment helpers into ``runtime/desktop/``, moving the
  destructive-intent classifier into ``agent/safety/``, and replacing
  the inline ``Agent.run_task`` ladder with a state-graph driver.
  Each of those is its own multi-commit task; doing them inside a
  single REWRITE commit would be too risky with ~40 active callers
  spread across ``api/``, ``channels/``, ``agents/orchestrator``, and
  the test suite.
* This commit locks the new public surface (``openakita.agent.core``)
  so v2 callers can already migrate; the deep slim-down lands during
  Phase 8 alongside ``core/`` removal.

Migration guidance
------------------
* New code: ``from openakita.agent.core import Agent``
* Legacy code continues to import from ``openakita.core.agent``
  unchanged; both paths refer to the same class.
"""

# REVAMP-FACADE-ALLOWED-UNTIL: P-RC-6
# This module is intentionally a thin re-export of its legacy
# `openakita.core.*` counterpart during P-RC-0..3. The real
# Phase-2 slim-down rewrite lands in P-RC-6 (continuation plan
# section 5/6/7); the sentinel above is the marker
# `tests/parity/test_no_facade.py` looks for to allow a small
# facade body during the early continuation phases. Removing this
# sentinel block in P-RC-6 is part of the gate review and forces
# the test to fall back to the SLOC heuristic.

from __future__ import annotations

from openakita.core.agent import (
    Agent,
    PromptStrategy,
    get_primary_agent,
    set_primary_agent,
)

__all__ = [
    "Agent",
    "PromptStrategy",
    "get_primary_agent",
    "set_primary_agent",
]
