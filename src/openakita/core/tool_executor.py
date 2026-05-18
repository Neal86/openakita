"""Thin shim re-exporting the v2 :mod:`openakita.agent.tools` symbols.

Per continuation plan section 5 (P-RC-4, P4.11), the legacy
~1818 LOC ``core.tool_executor`` god-class is collapsed to a
re-export shim. The real implementation lives at
:mod:`openakita.agent.tools`; the leaf helpers it composes
(truncate, overflow, retry policy) live under
:mod:`openakita.runtime.io` and :mod:`openakita.runtime.retry_policy`.

Lazy ``__getattr__`` is used so circular imports during package
initialisation are not triggered.
"""

from __future__ import annotations

__all__ = [
    "DEFAULT_TOOL_RESULT_MAX_CHARS",
    "MAX_TOOL_RESULT_CHARS",
    "OVERFLOW_MARKER",
    "ToolExecutor",
    "ToolExecutorProtocol",
    "ToolResultWithHint",
    "ToolSkipped",
    "save_overflow",
    "smart_truncate",
]


def __getattr__(name):
    if name in __all__:
        from openakita.agent import tools as _v2
        return getattr(_v2, name)
    # Fall back to the legacy module for the long tail of private
    # symbols (``_get_tool_result_max_chars``, ``_cleanup_overflow_files``,
    # ``ConfigHint``, etc.) that legacy callers still touch directly
    # via ``core.tool_executor.<name>``. Drop this fallback once
    # P-RC-7 deletes the legacy module entirely.
    from openakita.core import _tool_executor_legacy as _legacy
    if hasattr(_legacy, name):
        return getattr(_legacy, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
