from pathlib import Path

import pytest

from openakita.hermes.bindings import AgentHermesBinding, AgentHermesBindingStore
from openakita.hermes.client import HermesResponse
from openakita.hermes.models import HermesNode, HermesRuntimeProvider
from openakita.hermes.router import HermesRouter, HermesRoutingError
from openakita.hermes.runtime import execute_with_hermes_fallback
from openakita.hermes.store import HermesNodeStore


@pytest.mark.asyncio
async def test_router_fails_over_to_second_node(tmp_path: Path, monkeypatch):
    store = HermesNodeStore(tmp_path / "nodes.json")
    store.upsert(HermesNode(id="one", name="One", base_url="http://one", priority=1))
    store.upsert(HermesNode(id="two", name="Two", base_url="http://two", priority=2))

    calls = []

    async def fake_run(self, **kwargs):
        calls.append(self.node.id)
        if self.node.id == "one":
            raise RuntimeError("offline")
        return HermesResponse(content="ok", node_id=self.node.id)

    monkeypatch.setattr("openakita.hermes.client.HermesClient.run", fake_run)
    result = await HermesRouter(store).run(message="hi", agent_id="agent")

    assert result.content == "ok"
    assert calls == ["one", "two"]
    assert store.get("one").consecutive_failures == 1
    assert store.get("two").consecutive_failures == 0


@pytest.mark.asyncio
async def test_auto_runtime_falls_back_to_local(tmp_path: Path, monkeypatch):
    binding_path = tmp_path / "bindings.json"
    node_path = tmp_path / "nodes.json"
    AgentHermesBindingStore(binding_path).upsert(
        AgentHermesBinding(profile_id="a", runtime_provider=HermesRuntimeProvider.AUTO)
    )

    monkeypatch.setattr(
        "openakita.hermes.runtime.AgentHermesBindingStore",
        lambda: AgentHermesBindingStore(binding_path),
    )
    monkeypatch.setattr(
        "openakita.hermes.runtime.HermesRouter",
        lambda: HermesRouter(HermesNodeStore(node_path)),
    )

    async def local_runner():
        return "local-result"

    result = await execute_with_hermes_fallback(
        profile_id="a",
        message="hello",
        local_runner=local_runner,
    )
    assert result == "local-result"


@pytest.mark.asyncio
async def test_required_hermes_without_fallback_raises(tmp_path: Path, monkeypatch):
    binding_path = tmp_path / "bindings.json"
    node_path = tmp_path / "nodes.json"
    AgentHermesBindingStore(binding_path).upsert(
        AgentHermesBinding(
            profile_id="a",
            runtime_provider=HermesRuntimeProvider.HERMES,
            hermes_fallback_enabled=False,
        )
    )
    monkeypatch.setattr(
        "openakita.hermes.runtime.AgentHermesBindingStore",
        lambda: AgentHermesBindingStore(binding_path),
    )
    monkeypatch.setattr(
        "openakita.hermes.runtime.HermesRouter",
        lambda: HermesRouter(HermesNodeStore(node_path)),
    )

    with pytest.raises(HermesRoutingError):
        await execute_with_hermes_fallback(
            profile_id="a",
            message="hello",
            local_runner=lambda: None,
        )
