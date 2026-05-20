"""Contract suite for v2 OrgRuntime (P-RC-9 P9.6gamma).

Pins the public surface of
:class:`openakita.runtime.orgs.runtime.OrgRuntime` and the
~10 Protocol contracts it composes against the seven
sibling managers shipped in P9.6alpha-beta. Mirror the
P9.5d :class:`OrgManager` contract suite layout (16
cases) but covers the larger OrgRuntime surface
(~25 cases per the P9.6gamma brief).

This file lands in two commits:
* gamma-2a (this commit): 13 cases -- the 6
  CommandRuntimeProtocol method cases (10) + the 4
  Protocol surface cases (4 here -- new Protocol set) +
  the 3 OrgRuntime composition smokes (3 here).
* gamma-2b (next commit): 12 cases -- 4 concurrency, 1
  AgentBuilderProtocol Protocol surface, 1 OrgRuntime +
  OrgCommandService integration, 2 wall-clock SLA
  (perf_counter per ADR-0013 NIT-I-1 lesson).

The cases are stateless: each test constructs a fresh
:class:`OrgRuntime` against an in-process test-double
:class:`_CmdService` + :class:`_Lookup` so the suite stays
isolated (no cross-test bleed; no real persistence /
network / IM).
"""

from __future__ import annotations

import asyncio
from typing import Any

from openakita.runtime.orgs._runtime_dispatch import (
    TRACKER_CANCELLED,
    TRACKER_RUNNING,
)
from openakita.runtime.orgs.runtime import (
    EventBusProtocol,
    NodeLifecycleProtocol,
    OrgRuntime,
    RuntimeStateProtocol,
    _InMemoryEventBus,
    _InMemoryNodeLifecycle,
    _InMemoryRuntimeState,
)

# ---------------------------------------------------------------------------
# Shared test doubles -- minimal duck-typed shims; mirrors the parity harness.
# ---------------------------------------------------------------------------


class _Org:
    def __init__(self, org_id: str, *, state: str = "active") -> None:
        self.id = org_id
        self.state = state
        self.workspace_dir = None
        self.nodes = {"n1": type("N", (), {"role": "eng", "persona": "engineer"})()}


class _Lookup:
    def __init__(self, *, present: bool = True) -> None:
        self._present = present

    def get_org(self, org_id: str) -> Any:
        return _Org(org_id) if self._present else None


class _CmdService:
    """Async submit + cancel stub (CommandRuntimeProtocol facing)."""

    def __init__(self) -> None:
        self.submitted: list[tuple[str, str, str]] = []
        self.cancelled: list[tuple[str, str]] = []

    async def submit(self, *, org_id: str, target_node_id: str, content: str) -> dict[str, Any]:
        self.submitted.append((org_id, target_node_id, content))
        return {"command_id": f"cmd_{len(self.submitted)}", "status": "submitted"}

    async def cancel(self, org_id: str, command_id: str) -> None:
        self.cancelled.append((org_id, command_id))


def _make_runtime(
    *,
    lookup_present: bool = True,
    command_service: _CmdService | None = None,
    event_bus: _InMemoryEventBus | None = None,
) -> tuple[OrgRuntime, _CmdService, _InMemoryEventBus]:
    cs = command_service if command_service is not None else _CmdService()
    bus = event_bus if event_bus is not None else _InMemoryEventBus()
    rt = OrgRuntime(
        lookup=_Lookup(present=lookup_present),
        persistence=object(),
        lifecycle_emitter=object(),
        command_service=cs,
        event_bus=bus,
    )
    return rt, cs, bus


# ===========================================================================
# Group A -- CommandRuntimeProtocol method cases (10 cases)
# ===========================================================================


def test_contract_send_command_happy() -> None:
    """case id: send_command.happy"""
    rt, cs, _bus = _make_runtime()
    r = asyncio.run(rt.send_command("o1", "n1", "do it"))
    assert r["status"] == "submitted"
    assert r["org_id"] == "o1"
    assert r["node_id"] == "n1"
    assert r["command_id"] == "cmd_1"
    assert cs.submitted == [("o1", "n1", "do it")]


def test_contract_send_command_org_not_found() -> None:
    """case id: send_command.org_not_found"""
    rt, _cs, _bus = _make_runtime(lookup_present=False)
    r = asyncio.run(rt.send_command("nope", "n1", "x"))
    # v1 parity: error dict with reason ``org_not_found``.
    assert r == {"status": "error", "reason": "org_not_found", "org_id": "nope"}


def test_contract_cancel_user_command_running() -> None:
    """case id: cancel_user_command.running -> cancelled"""
    rt, cs, _bus = _make_runtime()
    r = asyncio.run(rt.send_command("o1", "n1", "task"))
    cid = r["command_id"]
    out = asyncio.run(rt.cancel_user_command("o1", cid))
    assert out == {"ok": True, "command_id": cid, "cancelled": True}
    assert cs.cancelled == [("o1", cid)]
    snap = rt.get_command_tracker_snapshot("o1", cid)
    assert snap is not None and snap["state"] == TRACKER_CANCELLED


def test_contract_cancel_user_command_missing() -> None:
    """case id: cancel_user_command.missing -> None"""
    rt, _cs, _bus = _make_runtime()
    out = asyncio.run(rt.cancel_user_command("o1", "no_such_cmd"))
    assert out is None  # v1 parity: unknown command_id returns None


def test_contract_cancel_user_command_idempotent() -> None:
    """case id: cancel_user_command.already_done"""
    rt, _cs, _bus = _make_runtime()
    r = asyncio.run(rt.send_command("o1", "n1", "task"))
    cid = r["command_id"]
    asyncio.run(rt.cancel_user_command("o1", cid))
    again = asyncio.run(rt.cancel_user_command("o1", cid))
    assert again is not None
    assert again["already_done"] is True
    assert again["state"] == TRACKER_CANCELLED


def test_contract_has_active_delegations_no_chains() -> None:
    """case id: has_active_delegations.no_chains"""
    rt, _cs, _bus = _make_runtime()
    r = asyncio.run(rt.send_command("o1", "n1", "task"))
    # No chains opened yet -> no active delegations.
    assert rt.has_active_delegations("o1", "n1") is False
    rt._dispatch.register_chain("o1", r["command_id"], "ch_a")
    assert rt.has_active_delegations("o1", "n1") is True


def test_contract_get_command_tracker_snapshot_running() -> None:
    """case id: get_command_tracker_snapshot.running"""
    rt, _cs, _bus = _make_runtime()
    r = asyncio.run(rt.send_command("o1", "n1", "ping"))
    snap = rt.get_command_tracker_snapshot("o1", r["command_id"])
    assert snap is not None
    assert snap["state"] == TRACKER_RUNNING
    assert snap["root_node_id"] == "n1"
    assert snap["chain_count"] == 0
    assert snap["accepted_chain_count"] == 0


def test_contract_get_command_tracker_snapshot_missing() -> None:
    """case id: get_command_tracker_snapshot.missing"""
    rt, _cs, _bus = _make_runtime()
    assert rt.get_command_tracker_snapshot("o1", "no_such") is None


def test_contract_get_event_store_default() -> None:
    """case id: get_event_store.default -> None (lazy-populate slot)"""
    rt, _cs, _bus = _make_runtime()
    # v1 parity: event_store is lazy-populated by the
    # lifecycle sibling; default OrgRuntime has no rows.
    assert rt.get_event_store("o1") is None


def test_contract_get_inbox_default() -> None:
    """case id: get_inbox.default -> None"""
    rt, _cs, _bus = _make_runtime()
    assert rt.get_inbox("o1") is None


# ===========================================================================
# Group B -- new Protocol surface cases (3 of 4 here; Agent Builder rides 2b)
# ===========================================================================


def test_contract_runtime_state_protocol_transitions() -> None:
    """case id: RuntimeStateProtocol.transition_org_state + get_org_state."""
    s: RuntimeStateProtocol = _InMemoryRuntimeState()
    assert s.get_org_state("o1") is None
    assert asyncio.run(s.transition_org_state("o1", "ACTIVE")) is True
    assert s.get_org_state("o1") == "ACTIVE"
    assert s.is_org_active("o1") is True
    assert asyncio.run(s.transition_org_state("o1", "STOPPED")) is True
    assert s.is_org_active("o1") is False


def test_contract_node_lifecycle_protocol_register_set_get() -> None:
    """case id: NodeLifecycleProtocol.register + set + get round trip."""
    state = _InMemoryRuntimeState()
    nl: NodeLifecycleProtocol = _InMemoryNodeLifecycle(state)
    nl.register_node("o1", "n1")
    # register_node defaults to IDLE.
    assert nl.get_node_status("o1", "n1") == "IDLE"
    asyncio.run(nl.set_node_status("o1", "n1", "BUSY"))
    assert nl.get_node_status("o1", "n1") == "BUSY"
    nl.deregister_node("o1", "n1")
    assert nl.get_node_status("o1", "n1") is None


def test_contract_event_bus_protocol_pubsub() -> None:
    """case id: EventBusProtocol.subscribe + emit + unsubscribe."""
    bus: EventBusProtocol = _InMemoryEventBus()
    received: list[dict[str, Any]] = []

    def handler(payload: dict[str, Any]) -> None:
        received.append(payload)

    bus.subscribe("e", handler)
    asyncio.run(bus.emit("e", {"k": "v"}))
    assert received == [{"k": "v"}]
    bus.unsubscribe("e", handler)
    asyncio.run(bus.emit("e", {"k": "v2"}))
    # No new events received after unsubscribe.
    assert received == [{"k": "v"}]
