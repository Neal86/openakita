"""Capability-aware routing and failover across Hermes nodes."""

from __future__ import annotations

import asyncio
import random
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any

from .client import HermesClient, HermesResponse
from .models import HermesNode, HermesRoutingPolicy
from .store import HermesNodeStore, get_hermes_store


class HermesRoutingError(RuntimeError):
    pass


class HermesRouter:
    def __init__(self, store: HermesNodeStore | None = None) -> None:
        self.store = store or get_hermes_store()
        self._round_robin: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    def candidates(
        self,
        *,
        node_ids: list[str] | None = None,
        required_capabilities: set[str] | None = None,
    ) -> list[HermesNode]:
        required = required_capabilities or set()
        allowed = set(node_ids or [])
        nodes = [
            node
            for node in self.store.list()
            if (not allowed or node.id in allowed) and node.available and node.supports(required)
        ]
        return sorted(nodes, key=lambda node: (node.priority, node.id))

    async def _ordered(
        self,
        nodes: list[HermesNode],
        policy: HermesRoutingPolicy,
        affinity_key: str,
    ) -> list[HermesNode]:
        if not nodes:
            return []
        if policy in {HermesRoutingPolicy.PRIORITY, HermesRoutingPolicy.PRIMARY_BACKUP}:
            return nodes
        if policy == HermesRoutingPolicy.LEAST_CONNECTIONS:
            return sorted(nodes, key=lambda n: (n.current_inflight / n.max_concurrency, n.priority))
        if policy == HermesRoutingPolicy.WEIGHTED:
            pool = [node for node in nodes for _ in range(max(1, node.weight))]
            first = random.choice(pool)
            return [first, *[node for node in nodes if node.id != first.id]]
        async with self._lock:
            index = self._round_robin[affinity_key] % len(nodes)
            self._round_robin[affinity_key] += 1
        return nodes[index:] + nodes[:index]

    async def _select(
        self,
        *,
        agent_id: str,
        node_ids: list[str] | None,
        policy: HermesRoutingPolicy | str,
        required_capabilities: set[str] | None,
    ) -> list[HermesNode]:
        if not isinstance(policy, HermesRoutingPolicy):
            policy = HermesRoutingPolicy(str(policy))
        nodes = self.candidates(node_ids=node_ids, required_capabilities=required_capabilities)
        ordered = await self._ordered(nodes, policy, agent_id)
        if not ordered:
            raise HermesRoutingError("No available Hermes node matches this Agent")
        return ordered

    async def run(
        self,
        *,
        message: str,
        agent_id: str,
        session_id: str = "",
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        node_ids: list[str] | None = None,
        policy: HermesRoutingPolicy | str = HermesRoutingPolicy.PRIORITY,
        required_capabilities: set[str] | None = None,
        allow_failover: bool = True,
    ) -> HermesResponse:
        ordered = await self._select(
            agent_id=agent_id,
            node_ids=node_ids,
            policy=policy,
            required_capabilities=required_capabilities,
        )
        errors: list[str] = []
        for index, node in enumerate(ordered):
            node.current_inflight += 1
            self.store.upsert(node)
            try:
                response = await HermesClient(node).run(
                    message=message,
                    agent_id=agent_id,
                    session_id=session_id,
                    system=system,
                    tools=tools,
                    metadata=metadata,
                )
                node.mark_success()
                return response
            except Exception as exc:
                node.mark_failure(str(exc))
                errors.append(f"{node.id}: {exc}")
                if not allow_failover or index == len(ordered) - 1:
                    break
            finally:
                node.current_inflight = max(0, node.current_inflight - 1)
                self.store.upsert(node)
        raise HermesRoutingError("All Hermes nodes failed: " + "; ".join(errors))

    async def run_stream(
        self,
        *,
        message: str,
        agent_id: str,
        session_id: str = "",
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        node_ids: list[str] | None = None,
        policy: HermesRoutingPolicy | str = HermesRoutingPolicy.PRIORITY,
        required_capabilities: set[str] | None = None,
        allow_failover: bool = True,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream native Hermes SSE events and fail over before output begins.

        Once a node has emitted any user-visible event, switching nodes would
        duplicate or corrupt the response. Therefore failover is only attempted
        when the failing node produced no events.
        """
        ordered = await self._select(
            agent_id=agent_id,
            node_ids=node_ids,
            policy=policy,
            required_capabilities=required_capabilities,
        )
        errors: list[str] = []
        for index, node in enumerate(ordered):
            emitted = False
            node.current_inflight += 1
            self.store.upsert(node)
            try:
                async for event in HermesClient(node).run_stream(
                    message=message,
                    agent_id=agent_id,
                    session_id=session_id,
                    system=system,
                    tools=tools or [],
                    metadata=metadata or {},
                ):
                    emitted = True
                    if isinstance(event, dict):
                        event.setdefault("node_id", node.id)
                    yield event
                node.mark_success()
                return
            except Exception as exc:
                node.mark_failure(str(exc))
                errors.append(f"{node.id}: {exc}")
                if emitted or not allow_failover or index == len(ordered) - 1:
                    break
            finally:
                node.current_inflight = max(0, node.current_inflight - 1)
                self.store.upsert(node)
        raise HermesRoutingError("All Hermes streaming nodes failed: " + "; ".join(errors))

    async def test_node(self, node_id: str) -> dict[str, Any]:
        node = self.store.get(node_id)
        if node is None:
            raise KeyError(node_id)
        try:
            result = await HermesClient(node).health()
            node.mark_success()
            ok = True
        except Exception as exc:
            node.mark_failure(str(exc))
            result = {"error": str(exc)}
            ok = False
        self.store.upsert(node)
        return {"ok": ok, "node": node.to_dict(), "result": result}
