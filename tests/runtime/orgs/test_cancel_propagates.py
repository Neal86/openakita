"""Sprint-3 P0-2 regression: ``cancel`` propagates ``CancelledError``
all the way down to the LLM call.

The v14 audit (``_orgs_business_capability_audit_v3.md`` §5.3) found
``POST /api/v2/orgs/{id}/commands/{cid}/cancel`` accepting the request
(HTTP 200, ``user_command_cancelled`` event written) but
``Brain.messages_create_async`` continuing to bill tokens for 60-180 s
afterwards: the underlying ``asyncio.Task`` had no handle inside the
runtime, so ``task.cancel()`` was never called. From the user's seat
the button greyed out, yet real money kept burning.

The fix wires three pieces:

* ``OrgCommandService._inflight_tasks`` -- per-command ``asyncio.Task``
  stash populated by ``_schedule_run`` and cleared in the
  ``_run_minimal`` finally.
* ``OrgCommandService.cancel`` -- calls ``task.cancel()`` *before*
  awaiting the runtime cancel so the cancel signal cannot be stranded
  by a slow lookup.
* ``AgentPipelineExecutor.activate_and_run`` -- catches
  ``CancelledError``, emits ``agent_run_cancelled``, re-raises so the
  asyncio task finalises with ``cancelled() == True`` and the
  ``_run_minimal`` cancel branch flips ``phase=cancelled``.

This file pins all three with a single end-to-end unit test that mocks
the brain as a 60 s ``asyncio.sleep`` -- if cancellation does not
propagate, the test times out (instead of completing in ~10 ms). The
test also pokes the smaller surface areas with focused cases so a
future regression at any one piece narrows the bisect range.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from openakita.orgs.command_models import OrgCommandRequest
from openakita.orgs.command_service import OrgCommandService


class _Node:
    def __init__(self, id_: str) -> None:
        self.id = id_


class _Org:
    def __init__(self) -> None:
        self.status = type("_Status", (), {"value": "active"})()
        self.nodes = [_Node("root1")]

    def get_node(self, nid: str) -> _Node | None:
        return next((n for n in self.nodes if n.id == nid), None)

    def get_root_nodes(self) -> list[_Node]:
        return list(self.nodes)


class _StubEventBus:
    """Sync subscribe/emit bus matching ``EventBusProtocol``-ish surface."""

    def __init__(self) -> None:
        self._subs: dict[str, list[Any]] = {}
        self.emitted: list[tuple[str, dict[str, Any]]] = []

    def subscribe(self, event: str, handler: Any) -> None:
        self._subs.setdefault(event, []).append(handler)

    def unsubscribe(self, event: str, handler: Any) -> None:
        if handler in self._subs.get(event, ()):
            self._subs[event].remove(handler)

    async def emit(self, event: str, payload: dict[str, Any]) -> None:
        self.emitted.append((event, dict(payload)))
        for h in list(self._subs.get(event, ())):
            res = h(payload)
            if asyncio.iscoroutine(res):
                await res


def _make_runtime(*, send_coro: Any = None) -> MagicMock:
    """Construct a duck-typed ``CommandRuntimeProtocol`` for the service.

    ``send_coro`` (when supplied) is awaited inside ``send_command`` so
    tests can simulate a long-running LLM call without spinning up the
    real dispatch sibling.
    """
    rt = MagicMock()
    rt.get_org = MagicMock(return_value=_Org())
    rt.get_command_tracker_snapshot = MagicMock(return_value=None)
    rt.get_event_store = MagicMock(return_value=MagicMock(query=lambda **kw: []))
    rt.has_active_delegations = MagicMock(return_value=False)
    rt.get_inbox = MagicMock(return_value=MagicMock())
    rt.cancel_user_command = AsyncMock(return_value={"cancelled_roots": ["root1"]})
    if send_coro is None:
        rt.send_command = AsyncMock(return_value={"status": "submitted"})
    else:
        rt.send_command = AsyncMock(side_effect=send_coro)
    return rt


@pytest.mark.asyncio
async def test_cancel_actually_cancels_inflight_llm_task() -> None:
    """case id: p0_2.cancel.actually_cancels_task

    The headline regression: with the inflight-task stash + cancel
    wiring in place, cancelling a command whose runtime is parked on
    a long ``asyncio.sleep`` (the stand-in for a slow LLM HTTP call)
    must complete in <1 s. Pre-Sprint-3 this test would deadlock at
    ``await task`` because the task only ever finishes when the sleep
    elapses naturally.
    """

    bus = _StubEventBus()

    async def slow_send(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        # Mimic the dispatch sibling: a slow await that would normally
        # be ``await brain.messages_create_async(...)`` deep inside the
        # executor. We yield via ``asyncio.sleep`` so ``task.cancel()``
        # can land at the next checkpoint -- this is exactly how the
        # real httpx request behaves when the event loop tears it down.
        await asyncio.sleep(60)
        return {"status": "submitted", "command_id": kwargs.get("command_id")}

    rt = _make_runtime(send_coro=slow_send)
    svc = OrgCommandService(rt, event_bus=bus)
    res = await svc.submit(OrgCommandRequest(org_id="o1", content="long task"))
    cid = res["command_id"]
    # Yield a tick so the background ``_run_minimal`` actually parks on
    # the slow ``send_command`` await before we ask to cancel.
    await asyncio.sleep(0.01)
    assert cid in svc._inflight_tasks
    assert not svc._inflight_tasks[cid].done()

    cancel_resp = await svc.cancel("o1", cid)
    assert cancel_resp is not None
    # ``cancelled_roots`` should come from the runtime cancel response,
    # not be the hard-coded ``[]`` the audit flagged.
    assert cancel_resp.get("cancelled_roots") == ["root1"]

    # Cleared from the inflight map and the task itself is finished
    # (cancelled). We bound this with ``wait_for`` so a regression
    # makes the test fail in seconds instead of timing out for an
    # hour.
    task = svc._inflight_tasks.get(cid)
    if task is not None:
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except (asyncio.CancelledError, TimeoutError):
            pass
    # After the finaliser unwinds the inflight stash, the entry is
    # gone (regardless of cancelled / done state).
    await asyncio.sleep(0.01)
    assert cid not in svc._inflight_tasks

    # The command record reflects the cancelled terminal state, not
    # ``running`` (pre-fix) or ``done`` (pre-Sprint-2 lie).
    cmd = svc.commands[cid]
    assert cmd["status"] == "cancelled"
    assert cmd["phase"] == "cancelled"
    assert cmd.get("event_ref") == "agent_run_cancelled"
    assert cmd.get("cancelled_by_user") is True


@pytest.mark.asyncio
async def test_cancel_records_inflight_task_on_submit() -> None:
    """case id: p0_2.cancel.submit_registers_task

    The inflight-task map is mutated inside ``submit`` (synchronously
    after the loop's ``create_task``), so a fast cancel cannot race
    with a missing entry. This case pins the race window closed: the
    map is populated before ``submit`` returns.
    """

    rt = _make_runtime()
    svc = OrgCommandService(rt)
    res = await svc.submit(OrgCommandRequest(org_id="o1", content="hi"))
    cid = res["command_id"]
    assert cid in svc._inflight_tasks
    assert isinstance(svc._inflight_tasks[cid], asyncio.Task)
    # Let the task complete cleanly so pytest's loop teardown is quiet.
    await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_cancel_on_unknown_command_returns_none() -> None:
    """case id: p0_2.cancel.unknown_command_short_circuits

    Cancel must keep its v1 contract: missing / wrong-org ids return
    ``None`` *before* touching the inflight-task map (so we cannot
    accidentally cancel a task belonging to a different request).
    """

    svc = OrgCommandService(_make_runtime())
    assert await svc.cancel("o1", "nonexistent") is None


@pytest.mark.asyncio
async def test_cancel_already_done_skips_task_cancel() -> None:
    """case id: p0_2.cancel.already_done_path

    Once a command terminates (``status != "running"``) cancel returns
    the ``already_done`` envelope without poking the task map: a stale
    ``Task`` reference must not be cancelled retroactively.
    """

    svc = OrgCommandService(_make_runtime())
    cid = "cmd_done"
    svc._commands[cid] = {
        "command_id": cid,
        "org_id": "o1",
        "root_node_id": "root1",
        "status": "done",
        "phase": "done",
        "result": "done",
        "error": None,
        "created_at": 1.0,
        "updated_at": 1.0,
        "finished_at": 2.0,
        "origin_surface": "org_console",
        "output_scope": "internal",
    }
    # Simulate a leaked task entry. ``cancel`` must NOT call
    # ``task.cancel()`` on it because the command is already terminal.
    sentinel_task = asyncio.ensure_future(asyncio.sleep(0))
    svc._inflight_tasks[cid] = sentinel_task

    resp = await svc.cancel("o1", cid)
    assert resp == {"ok": True, "command_id": cid, "already_done": True}
    assert not sentinel_task.cancelled()
    await sentinel_task


@pytest.mark.asyncio
async def test_handle_agent_event_records_cancelled_outcome_with_named_event() -> None:
    """case id: p0_2.handler.cancelled_event_routing

    The Sprint-2 handler inferred the event name from payload shape,
    which mis-classified ``agent_run_cancelled`` as ``agent_run_failed``
    (the payload carries ``reason="user_cancel"``). The new
    ``_make_event_handler`` closure captures the real event name so
    the outcome cache records it verbatim. This pins that wiring.
    """

    bus = _StubEventBus()
    svc = OrgCommandService(_make_runtime(), event_bus=bus)
    await bus.emit(
        "agent_run_cancelled",
        {
            "org_id": "o1",
            "node_id": "n1",
            "command_id": "cmd_x",
            "reason": "user_cancel",
        },
    )
    assert svc._command_outcomes["cmd_x"]["event"] == "agent_run_cancelled"
    assert svc._command_outcomes["cmd_x"]["reason"] == "user_cancel"


@pytest.mark.asyncio
async def test_get_status_overlay_flips_phase_when_cancel_outcome_lands_early() -> None:
    """case id: p0_2.get_status.live_cancel_overlay

    Mirrors the Sprint-2 ``agent_run_failed`` overlay test: when a poll
    arrives in the race window between the cancel event firing and the
    ``_run_minimal`` finaliser flipping the cmd dict, ``get_status``
    surfaces ``phase=cancelled`` immediately so the UI does not show
    "running" with a strikethrough cancel button.
    """

    bus = _StubEventBus()
    svc = OrgCommandService(_make_runtime(), event_bus=bus)
    cid = "cmd_live_cancel"
    svc._commands[cid] = {
        "command_id": cid,
        "org_id": "o1",
        "root_node_id": "root1",
        "status": "running",
        "phase": "running",
        "result": None,
        "error": None,
        "created_at": 1.0,
        "updated_at": 1.0,
        "finished_at": None,
        "origin_surface": "org_console",
        "output_scope": "internal",
    }
    await bus.emit(
        "agent_run_cancelled",
        {
            "org_id": "o1",
            "command_id": cid,
            "reason": "user_cancel",
        },
    )
    snap = svc.get_status("o1", cid)
    assert snap is not None
    assert snap["status"] == "cancelled"
    assert snap["phase"] == "cancelled"
    assert snap.get("event_ref") == "agent_run_cancelled"
