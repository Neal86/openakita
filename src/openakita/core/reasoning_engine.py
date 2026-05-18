"""Backward-compat shim for the legacy ReAct reasoning engine.

Real code now lives in :mod:`openakita.core._reasoning_engine_legacy`
(the renamed 8000+ LOC body). This shim re-exports the public surface
so existing ``from openakita.core.reasoning_engine import X`` imports
keep working unchanged.

P-RC-5 / P5.9 (continuation plan section 6): this commit performs
the rename + thin shim. The next commit (P5.10) lands the real v2
implementation in :mod:`openakita.agent.reasoning` and repoints
this shim's public surface to ``agent.reasoning``.
"""

from __future__ import annotations

__all__ = ["Checkpoint", "Decision", "DecisionType", "ReasoningEngine"]


def __getattr__(name):
    from openakita.core import _reasoning_engine_legacy as _legacy
    if hasattr(_legacy, name):
        return getattr(_legacy, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")