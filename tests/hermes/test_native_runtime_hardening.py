from __future__ import annotations

import asyncio

import pytest

from openakita.hermes.native_runtime import (
    NativeHermesExecutionError,
    NativeHermesRuntime,
)


@pytest.mark.asyncio
async def test_session_guard_wait_cancellation_does_not_leak_lock_refs() -> None:
    NativeHermesRuntime._session_locks.clear()
    NativeHermesRuntime._session_refs.clear()
    session = "openakita:support:cancelled-wait"

    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with NativeHermesRuntime._session_guard(session):
            entered.set()
            await release.wait()

    first = asyncio.create_task(holder())
    await entered.wait()

    async def waiter() -> None:
        async with NativeHermesRuntime._session_guard(session):
            pass

    second = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second

    release.set()
    await first
    assert session not in NativeHermesRuntime._session_refs
    assert session not in NativeHermesRuntime._session_locks


@pytest.mark.asyncio
async def test_installed_runtime_execution_failure_is_not_reported_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenAgent:
        def run_conversation(self, **_kwargs):
            raise RuntimeError("model failed")

    monkeypatch.setattr(
        NativeHermesRuntime,
        "_new_agent",
        classmethod(lambda cls, **kwargs: BrokenAgent()),
    )
    monkeypatch.setattr(
        "openakita.hermes.native_runtime.prepare_native_hermes_capabilities",
        lambda *args, **kwargs: type(
            "Snapshot",
            (),
            {"system_context": "", "metadata": lambda self: {}},
        )(),
    )

    with pytest.raises(NativeHermesExecutionError, match="model failed"):
        await NativeHermesRuntime.run(
            message="hello",
            agent_id="support",
            session_id="thread-1",
        )
