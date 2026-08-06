"""Runtime bridge used by Agent/Orchestrator call sites."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .bindings import AgentHermesBindingStore
from .models import HermesRuntimeProvider
from .router import HermesRouter, HermesRoutingError


async def execute_with_hermes_fallback(
    *,
    profile_id: str,
    message: str,
    session_id: str = "",
    system: str = "",
    tools: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
    local_runner: Callable[[], Awaitable[Any]] | None = None,
) -> Any:
    """Execute according to an Agent's persisted Hermes binding.

    ``local`` never contacts Hermes. ``hermes`` requires a remote result unless
    fallback is explicitly enabled. ``auto`` prefers Hermes and falls back to
    the supplied local runner when every eligible node fails.
    """
    binding = AgentHermesBindingStore().get(profile_id)
    if binding.runtime_provider == HermesRuntimeProvider.LOCAL:
        if local_runner is None:
            raise HermesRoutingError("Agent is configured for local runtime")
        return await local_runner()

    try:
        return await HermesRouter().run(
            message=message,
            agent_id=profile_id,
            session_id=session_id,
            system=system,
            tools=tools,
            metadata=metadata,
            node_ids=binding.hermes_node_ids,
            policy=binding.hermes_routing_policy,
            required_capabilities=set(binding.required_capabilities),
            allow_failover=True,
        )
    except HermesRoutingError:
        may_fallback = (
            binding.runtime_provider == HermesRuntimeProvider.AUTO
            or binding.hermes_fallback_enabled
        )
        if not may_fallback or local_runner is None:
            raise
        return await local_runner()
