"""Backward-compat shim for the legacy ReAct reasoning engine.

Real v2 code now lives in :mod:`openakita.agent.reasoning` (the
StateGraph-driven slim implementation that landed in P5.10); the
historical 8000+ LOC body lives at
:mod:`openakita.core._reasoning_engine_legacy`. This shim re-exports
the public surface so existing
``from openakita.core.reasoning_engine import X`` imports keep
working unchanged, with the same legacy-fallback pattern as the
sister shims for ``brain`` / ``tool_executor`` / ``context_manager``.
"""

from __future__ import annotations

__all__ = ["Checkpoint", "Decision", "DecisionType", "ReasoningEngine"]


def __getattr__(name):
    if name in __all__:
        from openakita.agent import reasoning as _v2
        return getattr(_v2, name)
    from openakita.core import _reasoning_engine_legacy as _legacy
    if hasattr(_legacy, name):
        return getattr(_legacy, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
