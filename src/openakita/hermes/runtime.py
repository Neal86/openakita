"""Runtime bridge used by Agent/Orchestrator call sites."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
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
    """Execute according to an Agent's persisted Hermes binding."""
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


async def stream_with_hermes_fallback(
    *,
    profile_id: str,
    message: str,
    session_id: str = "",
    system: str = "",
    tools: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
    local_stream_runner: Callable[[], AsyncIterator[dict[str, Any]]] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Stream from Hermes and fall back to the native local stream when allowed."""
    binding = AgentHermesBindingStore().get(profile_id)

    async def _yield_local() -> AsyncIterator[dict[str, Any]]:
        if local_stream_runner is None:
            raise HermesRoutingError("No local streaming runner is available")
        async for event in local_stream_runner():
            yield event

    if binding.runtime_provider == HermesRuntimeProvider.LOCAL:
        async for event in _yield_local():
            yield event
        return

    try:
        async for event in HermesRouter().run_stream(
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
        ):
            yield event
        return
    except HermesRoutingError:
        may_fallback = (
            binding.runtime_provider == HermesRuntimeProvider.AUTO
            or binding.hermes_fallback_enabled
        )
        if not may_fallback:
            raise

    async for event in _yield_local():
        yield event
