"""v22 P1: ``OrgCommandService`` supervisor hard ceiling.

Audit ``_v21_biz/_orgs_business_capability_audit_v10.md`` §19 caught
``cmd_1779887674678_00000035_f092f4`` pinning the
``_running_by_root[("org_X", "producer")]`` slot for 14m49s after the
supervisor task ought to have unwound. The trace showed the
``_schedule_run.run`` ``finally`` block never executed -- which only
happens when ``supervisor.run()`` itself is wedged inside a non-
cooperative await (LLM provider hang). Sprint-9 removed the legacy
wall-clock watchdog, so nothing rescued the slot.

The v22 fix in :class:`OrgCommandService._run_supervisor_with_hard_ceiling`
re-introduces an outer ``asyncio.wait_for`` budget around
``supervisor.run()``. When it fires:

1. ``supervisor.cancel_token.cancel("hard_ceiling")`` -- last-chance
   cooperative cancel so a checkpoint can be written.
2. A short ``asyncio.sleep(0.5)`` grace window.
3. Re-raise so the outer ``finally`` releases ``_running_by_root``,
   ``_active_supervisors``, ``_inflight_tasks``.

This file pins the contract.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from openakita.config import settings
from openakita.orgs.command_models import OrgCommandRequest
from openakita.orgs.command_service import OrgCommandService
from openakita.runtime.cancel_token import CancellationToken
from openakita.runtime.supervisor import FinalOutcome, SupervisorOutcome

# ---------------------------------------------------------------------------
# Test doubles -- mirror ``tests/runtime/orgs/test_supervisor_http_takeover.py``
# ---------------------------------------------------------------------------


class _Node:
    def __init__(self, id_: str) -> None:
        self.id = id_


class _Org:
    def __init__(self, *, roots: tuple[str, ...] = ("root1",)) -> None:
        self.status = type("_Status", (), {"value": "active"})()
        self.nodes = [_Node(r) for r in roots]

    def get_node(self, nid: str) -> _Node | None:
        return next((n for n in self.nodes if n.id == nid), None)

    def get_root_nodes(self) -> list[_Node]:
        return list(self.nodes)


class _FakeStallDetector:
    n_turns = 0
    n_stalls = 0


class _SleepForeverSupervisor:
    """Stand-in :class:`Supervisor` whose ``run()`` never returns naturally.

    Sits in a polling loop that observes the cooperative cancel token
    so the hard-ceiling-fired cancel still terminates promptly. Without
    the polling, the test would only finish on the asyncio.TimeoutError
    re-raise (which still works -- the slot release does not depend on
    cooperative unwind).
    """

    def __init__(self) -> None:
        self.cancel_token = CancellationToken()
        self.stall_detector = _FakeStallDetector()
        self.history: list[Any] = []
        self.n_replans = 0
        self.last_checkpoint_id: str | None = "cp-sleep-forever"
        self.resume_calls: list[str] = []
        self.run_started = asyncio.Event()
        self.cancel_observed: bool = False

    async def run(self) -> SupervisorOutcome:
        self.run_started.set()
        # The cooperative cancel path: cancel_token.cancel() -> we
        # observe it on the next poll and return CANCELLED. The hard
        # ceiling raises TimeoutError into ``_run_supervisor_with_hard_ceiling``
        # regardless, but observing the cancel proves the wrapper
        # called cancel BEFORE re-raising.
        while True:
            if self.cancel_token.is_cancelled():
                self.cancel_observed = True
                return SupervisorOutcome(
                    outcome=FinalOutcome.CANCELLED,
                    final_message="cancelled by token",
                    final_checkpoint_id=self.last_checkpoint_id,
                    n_turns=0,
                    n_replans=0,
                    reason=self.cancel_token.reason or "",
                )
            await asyncio.sleep(0.05)

    async def resume_from_checkpoint(self, checkpoint_id: str) -> _SleepForeverSupervisor:
        self.resume_calls.append(checkpoint_id)
        return self


def _make_runtime(*, org: _Org | None = None) -> MagicMock:
    """Minimal runtime mock satisfying the protocols the service touches."""

    rt = MagicMock()
    rt.get_org = MagicMock(return_value=org if org is not None else _Org())
    rt.get_command_tracker_snapshot = MagicMock(return_value=None)
    rt.get_event_store = MagicMock(return_value=MagicMock(query=lambda **kw: []))
    rt.has_active_delegations = MagicMock(return_value=False)
    rt.get_inbox = MagicMock(return_value=MagicMock())

    async def _async_cancel(*_a: Any, **_kw: Any) -> dict[str, Any]:
        return {"cancelled_roots": ["root1"]}

    rt.cancel_user_command = _async_cancel
    return rt


def _make_service(*, supervisor: _SleepForeverSupervisor) -> OrgCommandService:
    """Service whose ``_supervisor_factory`` always returns the stub."""

    def _factory(*, org_id: str, command_id: str, root_node_id: str, task: str,
                 executor: Any = None, brain: Any = None, stream: Any = None,
                 checkpointer: Any = None, cancel_token: Any = None) -> Any:
        return supervisor

    return OrgCommandService(_make_runtime(), supervisor_factory=_factory)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hard_ceiling_triggers_cancel_and_releases_slot(monkeypatch) -> None:
    """Hard ceiling = 2s; sleep-forever supervisor must release the slot."""
    monkeypatch.setattr(settings, "supervisor_hard_ceiling_s", 2, raising=False)

    supervisor = _SleepForeverSupervisor()
    svc = _make_service(supervisor=supervisor)

    res = await svc.submit(OrgCommandRequest(org_id="o1", content="hi"))
    cid = res["command_id"]
    assert res["status"] == "running"
    # The slot + inflight task entry are written synchronously in
    # submit; the supervisor registry entry is written by the
    # spawned coroutine, so we wait for it to actually enter
    # ``supervisor.run`` before asserting.
    assert ("o1", "root1") in svc._running_by_root
    assert cid in svc._inflight_tasks

    # Wait for the run coroutine to actually enter ``supervisor.run``.
    await asyncio.wait_for(supervisor.run_started.wait(), timeout=1.0)
    assert cid in svc._active_supervisors

    # Let the hard ceiling fire (2s wait_for + ~0.5s grace + overhead).
    # ``_schedule_run.run`` catches the re-raised TimeoutError as a
    # generic Exception and walks the finally cleanup; the wrapping
    # task itself completes normally. The contract we assert is that
    # bookkeeping is cleared and the cancel token fired.
    task = svc._inflight_tasks.get(cid)
    assert task is not None
    await asyncio.wait_for(task, timeout=6.0)

    # P1 acceptance criteria:
    assert ("o1", "root1") not in svc._running_by_root, "_running_by_root slot leaked"
    assert cid not in svc._active_supervisors, "_active_supervisors entry leaked"
    assert cid not in svc._inflight_tasks, "_inflight_tasks entry leaked"
    # The cancel token must have fired with the "hard_ceiling" reason.
    assert supervisor.cancel_token.is_cancelled(), "cancel_token.cancel was not invoked"
    assert "hard_ceiling" in supervisor.cancel_token.reason
    # And the outcome cache must record cancelled_by="hard_ceiling".
    outcome = svc._command_outcomes.get(cid) or {}
    assert outcome.get("cancelled_by") == "hard_ceiling"
    assert outcome.get("reason") == "supervisor_hard_ceiling_exceeded"


@pytest.mark.asyncio
async def test_hard_ceiling_disabled_when_setting_is_zero(monkeypatch) -> None:
    """``supervisor_hard_ceiling_s = 0`` keeps the Sprint-9 behaviour."""
    monkeypatch.setattr(settings, "supervisor_hard_ceiling_s", 0, raising=False)

    # Quick supervisor that finishes naturally so the test does not hang.
    class _QuickSupervisor:
        def __init__(self) -> None:
            self.cancel_token = CancellationToken()
            self.stall_detector = _FakeStallDetector()
            self.history: list[Any] = []
            self.n_replans = 0
            self.last_checkpoint_id = "cp-quick"
            self.resume_calls: list[str] = []

        async def run(self) -> SupervisorOutcome:
            await asyncio.sleep(0)
            return SupervisorOutcome(
                outcome=FinalOutcome.DONE,
                final_message="ok",
                final_checkpoint_id=self.last_checkpoint_id,
                n_turns=0,
                n_replans=0,
                reason="",
            )

        async def resume_from_checkpoint(self, checkpoint_id: str) -> Any:
            self.resume_calls.append(checkpoint_id)
            return self

    quick = _QuickSupervisor()

    def _factory(*, org_id: str, command_id: str, root_node_id: str, task: str,
                 executor: Any = None, brain: Any = None, stream: Any = None,
                 checkpointer: Any = None, cancel_token: Any = None) -> Any:
        return quick

    svc = OrgCommandService(_make_runtime(), supervisor_factory=_factory)
    res = await svc.submit(OrgCommandRequest(org_id="o1", content="hi"))
    cid = res["command_id"]
    task = svc._inflight_tasks.get(cid)
    assert task is not None
    await asyncio.wait_for(task, timeout=2.0)

    status = svc.get_status("o1", cid)
    assert status is not None
    assert status["status"] == "done"
    # The cancel token must NOT have been touched on the happy path.
    assert not quick.cancel_token.is_cancelled()
