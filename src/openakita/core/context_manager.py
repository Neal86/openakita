"""Thin shim re-exporting the v2 :mod:`openakita.agent.context` symbols.

Per continuation plan section 5 (P-RC-4, P4.15), the legacy
~1799 LOC ``core.context_manager`` god-class is collapsed to a
re-export shim. The real implementation lives at
:mod:`openakita.agent.context`; the leaf helpers it composes
(grouping, budget_trace, compress) live under
:mod:`openakita.runtime.context`.

Lazy ``__getattr__`` is used so circular imports during package
initialisation are not triggered.
"""

from __future__ import annotations

__all__ = [
    "CHARS_PER_TOKEN",
    "CHUNK_MAX_TOKENS",
    "CONTEXT_BOUNDARY_MARKER",
    "ContextManager",
    "ContextManagerProtocol",
    "ContextPressure",
]


def __getattr__(name):
    if name in __all__:
        from openakita.agent import context as _v2
        return getattr(_v2, name)
    # Long tail of private symbols still touched by legacy callers
    # (microcompact, _shared_estimate_tokens, etc.) -> fall through
    # to the preserved legacy module. Dropped in P-RC-7.
    from openakita.core import _context_manager_legacy as _legacy
    if hasattr(_legacy, name):
        return getattr(_legacy, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
