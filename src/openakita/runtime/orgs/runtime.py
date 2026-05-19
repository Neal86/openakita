"""OrgRuntime v2 Protocol + default-backend layer (P-RC-9 P9.6a0).

This is the **largest** of ADR-0011''s six Protocol-typed
subsystems. The v1 ``src/openakita/orgs/runtime.py`` is 6 355
LOC across 132 methods on a single ``OrgRuntime`` class; the
v2 rewrite splits the responsibility across ``runtime.py``
(this file: 3 NEW Protocols + 3 default in-memory backends +
[P9.6a] the ``OrgRuntime`` skeleton + ``CommandRuntimeProtocol``
surface) plus 7 sibling underscore-prefixed modules under
``runtime/orgs/`` (each <= 500 LOC per ADR-0014).

This commit (P9.6a0) lands the Protocol + default-backend
layer:

* Three NEW Protocols (each <= 5 methods per ADR-0011
  granularity ceiling):

  - :class:`RuntimeStateProtocol` (4 methods) -- org + node
    state machine ops (start / stop / get / is_active).
  - :class:`NodeLifecycleProtocol` (5 methods) -- per-node
    status transitions + message routing hook.
  - :class:`EventBusProtocol` (4 methods) -- pub / sub /
    broadcast for org + node lifecycle events.

* Default in-memory backends for the three new Protocols
  (sufficient for the unit / parity / contract suites and for
  smoke runs; production wiring composes the same Protocols
  with persistent / WebSocket-bridged backends).

The ``OrgRuntime`` class itself lands in P9.6a (next commit),
composing the 6 reused Protocols (from P9.1 / P9.3 / P9.4 /
P9.5) + these 3 new Protocols + implementing
``CommandRuntimeProtocol`` (P9.4 contract). Subsequent siblings
(``_runtime_event_bus.py`` P9.6b, ``_runtime_watchdog.py`` P9.6c,
``_runtime_lifecycle.py`` P9.6d) ride this turn; the heavy
siblings + parity + contract + G-RC-9.6 mini-gate ride
P9.6beta / P9.6gamma.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .blackboard import BlackboardBackendProtocol
from .command_service import OrgCommandServiceProtocol, OrgLookupProtocol
from .manager import OrgLifecycleEmitterProtocol, OrgPersistenceProtocol
from .node_scheduler import NodeSchedulerProtocol

if TYPE_CHECKING:  # pragma: no cover
    pass


# =====================================================================
# Three new Protocols (P9.6; each <= 5 methods per ADR-0011)
# =====================================================================


@runtime_checkable
class RuntimeStateProtocol(Protocol):
    """Org + node state machine surface (4 methods).

    Implementations track per-org running / paused / stopped
    states and the per-node IDLE / BUSY / ERROR transitions
    that drive the lifecycle + watchdog siblings.

    Default backend: :class:`_InMemoryRuntimeState` (this file).
    Production may swap in a SQLite-backed implementation
    once P-RC-10 hygiene runs land.
    """

    async def transition_org_state(
        self, org_id: str, target: str, *, reason: str | None = None
    ) -> bool: ...

    async def transition_node_state(
        self, org_id: str, node_id: str, target: str, *, reason: str | None = None
    ) -> bool: ...

    def get_org_state(self, org_id: str) -> str | None: ...

    def is_org_active(self, org_id: str) -> bool: ...


@runtime_checkable
class NodeLifecycleProtocol(Protocol):
    """Per-node lifecycle surface (5 methods).

    Implementations own the node status field on the
    ``Organization`` snapshot + the inbound message routing
    hook the messenger calls into.

    Default backend: :class:`_InMemoryNodeLifecycle`. Production
    composes with :class:`RuntimeStateProtocol` for the
    transition primitives.
    """

    async def set_node_status(
        self, org_id: str, node_id: str, new_status: str, *, reason: str | None = None
    ) -> None: ...

    def get_node_status(self, org_id: str, node_id: str) -> str | None: ...

    async def on_node_message(self, org_id: str, node_id: str, msg: Any) -> None: ...

    def register_node(self, org_id: str, node_id: str) -> None: ...

    def deregister_node(self, org_id: str, node_id: str) -> None: ...


@runtime_checkable
class EventBusProtocol(Protocol):
    """Pub / sub surface for org + node lifecycle (4 methods).

    Implementations fan events out to in-process subscribers
    (:meth:`subscribe` / :meth:`unsubscribe`) and to the
    WebSocket bridge (:meth:`broadcast_ws`). Default backend:
    :class:`_InMemoryEventBus`.
    """

    async def emit(self, event: str, payload: dict[str, Any]) -> None: ...

    async def broadcast_ws(self, event: str, data: dict[str, Any]) -> None: ...

    def subscribe(self, event: str, handler: Callable[[dict[str, Any]], Any]) -> None: ...

    def unsubscribe(self, event: str, handler: Callable[[dict[str, Any]], Any]) -> None: ...


# =====================================================================
# Default in-memory backends (P9.6a; sufficient for unit / parity tests)
# =====================================================================


class _InMemoryRuntimeState:
    """Dict-backed :class:`RuntimeStateProtocol` (default).

    Parity-faithful to v1 ``OrgRuntime`` semantics: an org is
    "active" iff a ``start_org`` transition succeeded since
    the last ``stop_org``; node statuses default to ``IDLE``.
    """

    def __init__(self) -> None:
        self._org_states: dict[str, str] = {}
        self._node_states: dict[tuple[str, str], str] = {}
        self._lock = asyncio.Lock()

    async def transition_org_state(
        self, org_id: str, target: str, *, reason: str | None = None
    ) -> bool:
        async with self._lock:
            self._org_states[org_id] = target
        return True

    async def transition_node_state(
        self, org_id: str, node_id: str, target: str, *, reason: str | None = None
    ) -> bool:
        async with self._lock:
            self._node_states[(org_id, node_id)] = target
        return True

    def get_org_state(self, org_id: str) -> str | None:
        return self._org_states.get(org_id)

    def is_org_active(self, org_id: str) -> bool:
        return self._org_states.get(org_id) == "ACTIVE"


class _InMemoryNodeLifecycle:
    """Dict-backed :class:`NodeLifecycleProtocol` (default)."""

    def __init__(self, state: RuntimeStateProtocol | None = None) -> None:
        self._state = state
        self._registered: set[tuple[str, str]] = set()
        self._statuses: dict[tuple[str, str], str] = {}

    async def set_node_status(
        self, org_id: str, node_id: str, new_status: str, *, reason: str | None = None
    ) -> None:
        self._statuses[(org_id, node_id)] = new_status
        if self._state is not None:
            await self._state.transition_node_state(org_id, node_id, new_status, reason=reason)

    def get_node_status(self, org_id: str, node_id: str) -> str | None:
        return self._statuses.get((org_id, node_id))

    async def on_node_message(self, org_id: str, node_id: str, msg: Any) -> None:
        # P9.6a: default backend is a sink; production wiring overrides via
        # _runtime_node_lifecycle.py (P9.6beta).
        return None

    def register_node(self, org_id: str, node_id: str) -> None:
        self._registered.add((org_id, node_id))
        self._statuses.setdefault((org_id, node_id), "IDLE")

    def deregister_node(self, org_id: str, node_id: str) -> None:
        self._registered.discard((org_id, node_id))
        self._statuses.pop((org_id, node_id), None)


class _InMemoryEventBus:
    """In-process :class:`EventBusProtocol` (default)."""

    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[dict[str, Any]], Any]]] = defaultdict(list)

    async def emit(self, event: str, payload: dict[str, Any]) -> None:
        for handler in list(self._subs.get(event, ())):
            res = handler(payload)
            if asyncio.iscoroutine(res):
                await res

    async def broadcast_ws(self, event: str, data: dict[str, Any]) -> None:
        # P9.6a: default backend is a no-op; production wiring overrides
        # via _runtime_event_bus.py (P9.6b lands real WS bridging).
        return None

    def subscribe(self, event: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        self._subs[event].append(handler)

    def unsubscribe(self, event: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        if handler in self._subs.get(event, ()):
            self._subs[event].remove(handler)


# =====================================================================
# OrgRuntime -- P9.6a scaffold (bodies ride P9.6alpha-d + P9.6beta)
# =====================================================================


class OrgRuntime:
    """v2 OrgRuntime -- charter subsystem #6 of ADR-0011.

    **Implements** :class:`CommandRuntimeProtocol` (the P9.4
    contract :class:`OrgCommandService` consumes -- closes the
    P9.4 dependency loop).

    **Composes** (DI via ``__init__``) the 6 reused Protocols
    + 3 new Protocols listed in the module docstring. The
    skeleton + ``__init__`` land in P9.6a; method bodies are
    filled across P9.6alpha-d (this turn) + P9.6beta (next
    turn).
    """

    def __init__(
        self,
        *,
        # Reused Protocols (composition from prior P9.x):
        lookup: OrgLookupProtocol,
        persistence: OrgPersistenceProtocol,
        lifecycle_emitter: OrgLifecycleEmitterProtocol,
        command_service: OrgCommandServiceProtocol | None = None,
        node_scheduler: NodeSchedulerProtocol | None = None,
        blackboard_backend: BlackboardBackendProtocol | None = None,
        # New Protocols (P9.6; defaults to in-memory backends):
        state: RuntimeStateProtocol | None = None,
        node_lifecycle: NodeLifecycleProtocol | None = None,
        event_bus: EventBusProtocol | None = None,
    ) -> None:
        self._lookup = lookup
        self._persistence = persistence
        self._lifecycle_emitter = lifecycle_emitter
        self._command_service = command_service
        self._node_scheduler = node_scheduler
        self._blackboard_backend = blackboard_backend
        self._state: RuntimeStateProtocol = state if state is not None else _InMemoryRuntimeState()
        self._node_lifecycle: NodeLifecycleProtocol = (
            node_lifecycle if node_lifecycle is not None else _InMemoryNodeLifecycle(self._state)
        )
        self._event_bus: EventBusProtocol = (
            event_bus if event_bus is not None else _InMemoryEventBus()
        )
        # Per-org accessors backing the OrgLookupProtocol +
        # CommandRuntimeProtocol surfaces. Populated lazily by
        # the lifecycle sibling (P9.6d).
        self._event_stores: dict[str, Any] = {}
        self._inboxes: dict[str, Any] = {}
        self._watchdog_tasks: dict[str, asyncio.Task[None]] = {}
        self._idle_probe_tasks: dict[str, asyncio.Task[None]] = {}

    # ------------------------------------------------------------------
    # OrgLookupProtocol delegation (Protocol satisfied via composition)
    # ------------------------------------------------------------------

    def get_org(self, org_id: str) -> Any:
        return self._lookup.get_org(org_id)

    # ------------------------------------------------------------------
    # CommandRuntimeProtocol -- 6 stub methods (P9.6beta fills bodies)
    # ------------------------------------------------------------------

    async def send_command(self, org_id: str, target_node_id: str, content: str) -> dict[str, Any]:
        """Send a user command to an org node (P9.4 contract).

        Body lands in ``_runtime_dispatch.py`` (P9.6beta).
        """
        raise NotImplementedError("P9.6beta: _runtime_dispatch.py")

    async def cancel_user_command(self, org_id: str, command_id: str) -> dict[str, Any] | None:
        """Cancel an in-flight user command (P9.4 contract)."""
        raise NotImplementedError("P9.6beta: _runtime_dispatch.py")

    def has_active_delegations(self, org_id: str, root_node_id: str) -> bool:
        raise NotImplementedError("P9.6beta: _runtime_dispatch.py")

    def get_command_tracker_snapshot(self, org_id: str, command_id: str) -> dict[str, Any] | None:
        raise NotImplementedError("P9.6beta: _runtime_dispatch.py")

    def get_event_store(self, org_id: str) -> Any:
        return self._event_stores.get(org_id)

    def get_inbox(self, org_id: str) -> Any:
        return self._inboxes.get(org_id)


def get_runtime() -> OrgRuntime | None:
    """Return the process-wide :class:`OrgRuntime` singleton.

    P9.6a returns ``None``; the factory wiring lives in the
    lifecycle sibling (P9.6d) which sets the singleton on
    first ``start()``.
    """

    return _RUNTIME_SINGLETON


_RUNTIME_SINGLETON: OrgRuntime | None = None
