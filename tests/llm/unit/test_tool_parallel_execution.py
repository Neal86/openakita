import asyncio
from types import SimpleNamespace

import pytest

from openakita.agent.tools import ToolExecutor


class _Registry:
    def get_handler_name_for_tool(self, _tool_name: str):
        return None

    def check_concurrency_safe(self, _tool_name: str, _tool_input: dict):
        return None

    def list_tools(self):
        return ["read_file", "write_file"]


async def _run_batch(tool_name: str) -> int:
    executor = ToolExecutor(_Registry(), max_parallel=2)
    executor._emit_tool_intent_previews = lambda *_args, **_kwargs: None
    executor.check_permission = lambda *_args, **_kwargs: SimpleNamespace(
        behavior="allow", metadata={}
    )

    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def fake_execute(
        name,
        tool_input,
        policy_result,
        *,
        session_id=None,
        execution_context=None,
    ):
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.05)
        async with lock:
            active -= 1
        return f"ok:{name}:{tool_input['n']}", None

    executor.execute_tool_with_policy = fake_execute
    results, executed, _ = await executor.execute_batch(
        [
            {"id": "call-1", "name": tool_name, "input": {"n": 1}},
            {"id": "call-2", "name": tool_name, "input": {"n": 2}},
        ],
        allow_interrupt_checks=False,
    )
    assert len(results) == 2
    assert executed == [tool_name, tool_name]
    return peak


@pytest.mark.asyncio
async def test_concurrency_safe_tools_execute_in_parallel():
    assert await _run_batch("read_file") == 2


@pytest.mark.asyncio
async def test_mutating_tools_remain_serial():
    assert await _run_batch("write_file") == 1
