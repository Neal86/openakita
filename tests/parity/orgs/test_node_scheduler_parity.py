"""Parity fixtures for OrgNodeScheduler v1 -> v2 (P-RC-9 P9.3c).

Each :class:`ParityCase` exercises the same scripted scenario
against v1 ``openakita.orgs.node_scheduler.OrgNodeScheduler``
and the v2
``openakita.runtime.orgs.node_scheduler.OrgNodeScheduler`` and
asserts equality on a normalised :class:`ParityResult` via
:func:`assert_parity`.

Per P-RC-9-PLAN section 5.2 (NodeScheduler parity contract):
*assert next-fire-time computed by both paths is within 1 ms
of each other*. v1 has no exposed next-fire-time helper -- the
computation is inlined in
``_schedule_loop`` -- so the v1 runner re-implements the
literal formula from v1''s source (``now + interval_s`` for
INTERVAL/CRON; ``datetime.fromisoformat(run_at)`` UTC-coerced
for ONCE) with a source-line comment for traceability. The
1-ms tolerance is the safety net for any unintended drift.

For the dispatch-prompt case the v1 path actually drives v1''s
``OrgNodeScheduler.trigger_once`` against a MagicMock runtime
(same pattern as ``tests/orgs/test_node_scheduler.py``) so the
v1 prompt is captured from a real v1 call rather than
re-implemented. v2 calls
``runtime.orgs.node_scheduler.OrgNodeScheduler.trigger_once``
against an analogous stub dispatcher / store / probe. The
ignore set strips the ``\u65f6\u95f4: <iso>`` timestamp line
because both paths read ``datetime.now`` at dispatch time.

P9.0i shipped a single ``xfail`` placeholder; this commit
replaces it wholesale. Four cases per P9.3 charter:

* ``scheduler_next_fire_interval``    -- INTERVAL 600 s.
* ``scheduler_next_fire_once``        -- ONCE 120 s ahead.
* ``scheduler_next_fire_cron``        -- CRON falls through
  to interval timing in both v1 and v2 (the documented v1
  quirk preserved in v2 ``compute_next_fire_time``).
* ``scheduler_dispatch_prompt``       -- v1 vs v2
  ``trigger_once`` produce the same prompt structure modulo
  the ``\u65f6\u95f4`` timestamp line.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.parity.harness import ParityCase, ParityResult, assert_parity

# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


# Strict 1-ms tolerance per P-RC-9-PLAN section 5.2.
_FIRE_TIME_TOLERANCE_MS = 1.0


def _strip_timestamp_line(prompt: str) -> str:
    """Remove the ``\u65f6\u95f4: <iso>`` line so prompts compare structurally."""
    return "\n".join(line for line in prompt.split("\n") if not line.startswith("\u65f6\u95f4: "))


# ---------------------------------------------------------------------------
# Runners -- next-fire-time
# ---------------------------------------------------------------------------


def _next_fire_v1(case: ParityCase, now: datetime) -> ParityResult:
    """v1 next-fire formula re-implementing v1 ``_schedule_loop`` inline.

    Source reference: ``src/openakita/orgs/node_scheduler.py``
    around lines 115-125 (ONCE branch:
    ``target = datetime.fromisoformat(sched.run_at)``;
    INTERVAL / CRON fall-through:
    ``current_interval = sched.interval_s ... else 3600`` ->
    ``asyncio.sleep(current_interval)``).
    """
    from openakita.orgs.models import NodeSchedule as V1NS
    from openakita.orgs.models import ScheduleType as V1ST

    sched = V1NS(
        name=case.inputs["name"],
        schedule_type=V1ST(case.inputs["schedule_type"]),
        cron=case.inputs.get("cron"),
        interval_s=case.inputs.get("interval_s"),
        run_at=case.inputs.get("run_at"),
        prompt=case.inputs["prompt"],
    )
    if sched.schedule_type == V1ST.ONCE:
        if not sched.run_at:
            target = now
        else:
            target = datetime.fromisoformat(sched.run_at)
            if target.tzinfo is None:
                target = target.replace(tzinfo=UTC)
    else:
        interval = sched.interval_s if sched.interval_s and sched.interval_s > 0 else 3600
        target = now + timedelta(seconds=interval)
    return ParityResult(
        final_message="next_fire",
        success=True,
        extras={"fire_iso": target.isoformat()},
    )


def _next_fire_v2(case: ParityCase, now: datetime) -> ParityResult:
    """v2 next-fire via :func:`compute_next_fire_time` pure helper."""
    from openakita.runtime.orgs.node_scheduler import compute_next_fire_time
    from openakita.runtime.orgs.scheduler_models import NodeSchedule as V2NS
    from openakita.runtime.orgs.scheduler_models import ScheduleType as V2ST

    sched = V2NS(
        name=case.inputs["name"],
        schedule_type=V2ST(case.inputs["schedule_type"]),
        cron=case.inputs.get("cron"),
        interval_s=case.inputs.get("interval_s"),
        run_at=case.inputs.get("run_at"),
        prompt=case.inputs["prompt"],
    )
    target = compute_next_fire_time(sched, now)
    return ParityResult(
        final_message="next_fire",
        success=True,
        extras={"fire_iso": target.isoformat()},
    )


# ---------------------------------------------------------------------------
# Runners -- dispatch prompt (v1 trigger_once vs v2 trigger_once)
# ---------------------------------------------------------------------------


def _v1_capture_prompt(case: ParityCase) -> str:
    """Run v1 ``OrgNodeScheduler.trigger_once`` end-to-end and capture the prompt."""
    import asyncio

    from openakita.orgs.models import NodeSchedule as V1NS
    from openakita.orgs.models import ScheduleType as V1ST
    from openakita.orgs.node_scheduler import OrgNodeScheduler as V1Sched

    rt = MagicMock()
    sched = V1NS(
        name=case.inputs["name"],
        schedule_type=V1ST(case.inputs["schedule_type"]),
        interval_s=case.inputs.get("interval_s"),
        prompt=case.inputs["prompt"],
        report_condition=case.inputs.get("report_condition", "on_issue"),
        report_to=case.inputs.get("report_to"),
    )
    rt._manager.get_node_schedules = MagicMock(return_value=[sched])
    rt._manager.save_node_schedules = MagicMock()
    rt.get_event_store = MagicMock(return_value=MagicMock())
    rt.send_command = AsyncMock(return_value={"result": "ok"})

    scheduler = V1Sched(rt)
    asyncio.run(scheduler.trigger_once("o", "n", sched.id))
    # send_command(org_id, node_id, prompt) -> positional [2]
    return rt.send_command.call_args[0][2]


def _v2_capture_prompt(case: ParityCase) -> str:
    """Run v2 ``OrgNodeScheduler.trigger_once`` end-to-end and capture the prompt."""
    import asyncio

    from openakita.runtime.orgs.node_scheduler import OrgNodeScheduler as V2Sched
    from openakita.runtime.orgs.scheduler_models import NodeSchedule as V2NS
    from openakita.runtime.orgs.scheduler_models import ScheduleType as V2ST

    captured: dict[str, str] = {}

    class CapDispatcher:
        async def dispatch(self, org_id: str, node_id: str, prompt: str) -> dict:
            captured["prompt"] = prompt
            return {"result": "ok"}

    sched = V2NS(
        name=case.inputs["name"],
        schedule_type=V2ST(case.inputs["schedule_type"]),
        interval_s=case.inputs.get("interval_s"),
        prompt=case.inputs["prompt"],
        report_condition=case.inputs.get("report_condition", "on_issue"),
        report_to=case.inputs.get("report_to"),
    )

    class CapStore:
        def __init__(self) -> None:
            self._scheds = [sched]

        def get_node_schedules(self, org_id: str, node_id: str):
            return list(self._scheds)

        def save_node_schedules(self, org_id: str, node_id: str, scheds) -> None:
            self._scheds = list(scheds)

    class CapProbe:
        def is_node_runnable(self, org_id: str, node_id: str) -> bool:
            return True

        def emit_event(self, org_id: str, event_type: str, node_id: str, payload: dict) -> None:
            pass

    scheduler = V2Sched(CapDispatcher(), CapStore(), CapProbe())
    asyncio.run(scheduler.trigger_once("o", "n", sched.id))
    return captured["prompt"]


# ---------------------------------------------------------------------------
# Cases + dispatch
# ---------------------------------------------------------------------------


_NOW = datetime(2026, 5, 19, 12, 0, 0, tzinfo=UTC)


CASES: list[ParityCase] = [
    ParityCase(
        id="scheduler_next_fire_interval",
        kind="node_scheduler",
        inputs={
            "op": "next_fire",
            "name": "int600",
            "schedule_type": "interval",
            "interval_s": 600,
            "prompt": "check",
        },
    ),
    ParityCase(
        id="scheduler_next_fire_once",
        kind="node_scheduler",
        inputs={
            "op": "next_fire",
            "name": "once120",
            "schedule_type": "once",
            "run_at": (_NOW + timedelta(seconds=120)).isoformat(),
            "prompt": "do",
        },
    ),
    ParityCase(
        id="scheduler_next_fire_cron",
        kind="node_scheduler",
        inputs={
            "op": "next_fire",
            "name": "cron300",
            "schedule_type": "cron",
            "cron": "*/5 * * * *",
            "interval_s": 300,
            "prompt": "poll",
        },
    ),
    ParityCase(
        id="scheduler_dispatch_prompt",
        kind="node_scheduler",
        inputs={
            "op": "dispatch_prompt",
            "name": "\u5de1\u68c0",  # \u5de1\u68c0 = inspection
            "schedule_type": "interval",
            "interval_s": 3600,
            "prompt": "\u68c0\u67e5\u670d\u52a1\u72b6\u6001",
            "report_condition": "on_issue",
            "report_to": "\u9886\u5bfc",
        },
    ),
]


def _run_case(case: ParityCase) -> tuple[ParityResult, ParityResult]:
    if case.inputs["op"] == "next_fire":
        return _next_fire_v1(case, _NOW), _next_fire_v2(case, _NOW)
    if case.inputs["op"] == "dispatch_prompt":
        v1_prompt = _strip_timestamp_line(_v1_capture_prompt(case))
        v2_prompt = _strip_timestamp_line(_v2_capture_prompt(case))
        v1_res = ParityResult(final_message="prompt", success=True, extras={"prompt": v1_prompt})
        v2_res = ParityResult(final_message="prompt", success=True, extras={"prompt": v2_prompt})
        return v1_res, v2_res
    raise KeyError(f"unknown op: {case.inputs['op']}")


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_node_scheduler_parity(case: ParityCase) -> None:
    """v1 vs v2 OrgNodeScheduler parity (P-RC-9 P9.3c, 4 cases)."""
    v1, v2 = _run_case(case)
    if case.inputs["op"] == "next_fire":
        # Wall-clock 1-ms safety net (P-RC-9-PLAN section 5.2). Both
        # paths feed off the same ``_NOW`` constant so the delta is
        # effectively zero; the explicit assertion guards against
        # later drift if either path changes the formula.
        from datetime import datetime as _dt

        t1 = _dt.fromisoformat(v1.extras["fire_iso"])
        t2 = _dt.fromisoformat(v2.extras["fire_iso"])
        delta_ms = abs((t1 - t2).total_seconds()) * 1000.0
        assert delta_ms < _FIRE_TIME_TOLERANCE_MS, (
            f"next-fire-time drift {delta_ms:.3f} ms exceeds 1 ms budget for {case.id}"
        )
    assert_parity(v1, v2, case=case)
