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
        self._capacity: dict[str, tuple[int, asyncio.Semaphore]] = {}

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

    def _semaphore(self, node: HermesNode) -> asyncio.Semaphore:
        limit = max(1, int(node.max_concurrency or 1))
        existing = self._capacity.get(node.id)
        if existing is None or existing[0] != limit:
            semaphore = asyncio.Semaphore(limit)
            self._capacity[node.id] = (limit, semaphore)
            return semaphore
        return existing[1]

    async def _set_inflight(self, node: HermesNode, delta: int) -> None:
        async with self._lock:
            latest = self.store.get(node.id) or node
            latest.current_inflight = max(0, int(latest.current_inflight) + delta)
            node.current_inflight = latest.current_inflight
            self.store.upsert(latest)

    async def _mark_success(self, node: HermesNode) -> None:
        """Update health without overwriting another request's inflight count."""
        async with self._lock:
            latest = self.store.get(node.id) or node
            latest.mark_success()
            self.store.upsert(latest)
            node.health_status = latest.health_status
            node.consecutive_failures = latest.consecutive_failures
            node.last_success_at = latest.last_success_at
            node.last_error = latest.last_error

    async def _mark_failure(self, node: HermesNode, error: str) -> None:
        """Update health from the latest persisted node snapshot."""
        async with self._lock:
            latest = self.store.get(node.id) or node
            latest.mark_failure(error)
            self.store.upsert(latest)
            node.health_status = latest.health_status
            node.consecutive_failures = latest.consecutive_failures
            node.last_success_at = latest.last_success_at
            node.last_error = latest.last_error

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
            return sorted(
                nodes,
                key=lambda n: (
                    n.current_inflight / max(1, n.max_concurrency),
                    n.priority,
                ),
            )
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
            semaphore = self._semaphore(node)
            await semaphore.acquire()
            await self._set_inflight(node, 1)
            try:
                response = await HermesClient(node).run(
                    message=message,
                    agent_id=agent_id,
                    session_id=session_id,
                    system=system,
                    tools=tools,
                    metadata=metadata,
                )
                await self._mark_success(node)
                return response
            except Exception as exc:
                await self._mark_failure(node, str(exc))
                errors.append(f"{node.id}: {exc}")
                if not allow_failover or index == len(ordered) - 1:
                    break
            finally:
                await self._set_inflight(node, -1)
                semaphore.release()
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
        """Stream native Hermes SSE events and fail over before output begins."""
        ordered = await self._select(
            agent_id=agent_id,
            node_ids=node_ids,
            policy=policy,
            required_capabilities=required_capabilities,
        )
        errors: list[str] = []
        for index, node in enumerate(ordered):
            emitted = False
            semaphore = self._semaphore(node)
            await semaphore.acquire()
            await self._set_inflight(node, 1)
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
                await self._mark_success(node)
                return
            except Exception as exc:
                await self._mark_failure(node, str(exc))
                errors.append(f"{node.id}: {exc}")
                if emitted or not allow_failover or index == len(ordered) - 1:
                    break
            finally:
                await self._set_inflight(node, -1)
                semaphore.release()
        raise HermesRoutingError("All Hermes streaming nodes failed: " + "; ".join(errors))

    async def test_node(self, node_id: str) -> dict[str, Any]:
        node = self.store.get(node_id)
        if node is None:
            raise KeyError(node_id)
        try:
            result = await HermesClient(node).health()
            await self._mark_success(node)
            ok = True
        except Exception as exc:
            await self._mark_failure(node, str(exc))
            result = {"error": str(exc)}
            ok = False
        latest = self.store.get(node_id) or node
        return {"ok": ok, "node": latest.to_dict(), "result": result}
