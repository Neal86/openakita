from __future__ import annotations

import sys
import types

import pytest

from openakita.hermes.models import HermesNode
from openakita.hermes.client import HermesClient
from openakita.hermes.native_runtime import NativeHermesRuntime


def test_native_session_ids_are_agent_scoped() -> None:
    assert NativeHermesRuntime._scoped_session_id("sales", "thread-1") == "openakita:sales:thread-1"
    assert NativeHermesRuntime._scoped_session_id("support", "thread-1") == "openakita:support:thread-1"
    assert NativeHermesRuntime._scoped_session_id("sales", "") == "openakita:sales:default"


def test_native_agent_kwargs_route_to_openakita_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAKITA_HERMES_LLM_BASE_URL", "http://127.0.0.1:18900/v1/")
    monkeypatch.setenv("OPENAKITA_HERMES_LLM_API_KEY", "internal-test")
    kwargs = NativeHermesRuntime._agent_kwargs(agent_id="support", session_id="abc")
    assert kwargs["base_url"] == "http://127.0.0.1:18900/v1"
    assert kwargs["api_key"] == "internal-test"
    assert kwargs["provider"] == "custom"
    assert kwargs["model"] == "agent:support"
    assert kwargs["session_id"] == "openakita:support:abc"


@pytest.mark.asyncio
async def test_native_run_uses_in_process_aiagent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            calls["kwargs"] = kwargs

        def run_conversation(self, **kwargs):
            calls["conversation"] = kwargs
            return {"final_response": "native-ok"}

    fake_module = types.ModuleType("run_agent")
    fake_module.AIAgent = FakeAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_module)

    result = await NativeHermesRuntime.run(
        message="hello",
        agent_id="support",
        session_id="thread-a",
        system="system prompt",
    )

    assert result["content"] == "native-ok"
    assert result["metadata"]["runtime"] == "native"
    assert result["metadata"]["hermes_session_id"] == "openakita:support:thread-a"
    assert calls["conversation"] == {
        "user_message": "hello",
        "system_message": "system prompt",
        "task_id": "openakita:support:thread-a",
    }


@pytest.mark.asyncio
async def test_client_native_transport_never_uses_http(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(**kwargs):
        return {"content": "ok", "usage": {}, "metadata": {"runtime": "native"}}

    monkeypatch.setattr(NativeHermesRuntime, "run", fake_run)
    node = HermesNode(id="embedded", name="Embedded", base_url="native://embedded")
    response = await HermesClient(node).run(message="hello", agent_id="agent-1")
    assert response.content == "ok"
    assert response.metadata["runtime"] == "native"
