import asyncio
from types import SimpleNamespace

import pytest

from openakita.core._tool_executor_legacy import ToolExecutor


class _Registry:
    def check_concurrency_safe(self, tool_name: str, tool_input: dict):
        if tool_name == "read_file":
            return True
        if tool_name == "write_file":
            return False
        return None

    def get_handler_name_for_tool(self, tool_name: str):
        return "filesystem"

    def has_tool(self, tool_name: str) -> bool:
        return tool_name in {"read_file", "write_file"}

    def list_tools(self):
        return ["read_file", "write_file"]


@pytest.mark.asyncio
async def test_read_only_tools_really_overlap(monkeypatch):
    executor = ToolExecutor(_Registry(), max_parallel=2)
    monkeypatch.setattr(
        executor,
        "check_permission",
        lambda _name, _input: SimpleNamespace(behavior="allow", metadata={}),
    )

    active = 0
    peak = 0

    async def fake_execute(tool_name, tool_input, policy_result, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.05)
        active -= 1
        return f"ok:{tool_input['path']}", None

    monkeypatch.setattr(executor, "execute_tool_with_policy", fake_execute)

    results, executed, _ = await executor.execute_batch(
        [
            {"id": "r1", "name": "read_file", "input": {"path": "a.txt"}},
            {"id": "r2", "name": "read_file", "input": {"path": "b.txt"}},
        ],
        allow_interrupt_checks=False,
    )

    assert peak == 2
    assert executed == ["read_file", "read_file"]
    assert [row["tool_use_id"] for row in results] == ["r1", "r2"]


@pytest.mark.asyncio
async def test_write_tools_stay_serialized(monkeypatch):
    executor = ToolExecutor(_Registry(), max_parallel=2)
    monkeypatch.setattr(
        executor,
        "check_permission",
        lambda _name, _input: SimpleNamespace(behavior="allow", metadata={}),
    )

    active = 0
    peak = 0

    async def fake_execute(tool_name, tool_input, policy_result, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.05)
        active -= 1
        return f"ok:{tool_input['path']}", None

    monkeypatch.setattr(executor, "execute_tool_with_policy", fake_execute)

    results, executed, _ = await executor.execute_batch(
        [
            {"id": "w1", "name": "write_file", "input": {"path": "a.txt"}},
            {"id": "w2", "name": "write_file", "input": {"path": "b.txt"}},
        ],
        allow_interrupt_checks=False,
    )

    assert peak == 1
    assert executed == ["write_file", "write_file"]
    assert [row["tool_use_id"] for row in results] == ["w1", "w2"]
