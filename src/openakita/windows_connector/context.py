from __future__ import annotations

from contextvars import ContextVar

# Executor-owned context. Tool model inputs never carry this value, preventing
# prompt/tool arguments from impersonating a different Agent grant.
current_agent_profile_id: ContextVar[str] = ContextVar(
    "openakita_windows_connector_agent_profile_id",
    default="",
)
