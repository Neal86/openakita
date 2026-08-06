from pathlib import Path

from openakita.hermes.bindings import AgentHermesBinding, AgentHermesBindingStore
from openakita.hermes.models import HermesHealthStatus, HermesNode, HermesRuntimeProvider
from openakita.hermes.store import HermesNodeStore


def test_node_store_roundtrip(tmp_path: Path):
    store = HermesNodeStore(tmp_path / "hermes_nodes.json")
    node = HermesNode(id="h1", name="Hermes 1", base_url="http://hermes-1:8000/")
    store.upsert(node)
    loaded = store.get("h1")
    assert loaded is not None
    assert loaded.base_url == "http://hermes-1:8000"
    assert loaded.health_status == HermesHealthStatus.UNKNOWN


def test_binding_defaults_are_backward_compatible(tmp_path: Path):
    store = AgentHermesBindingStore(tmp_path / "bindings.json")
    binding = store.get("legacy-agent")
    assert binding.runtime_provider == HermesRuntimeProvider.LOCAL
    assert binding.hermes_node_ids == []


def test_binding_roundtrip(tmp_path: Path):
    store = AgentHermesBindingStore(tmp_path / "bindings.json")
    store.upsert(
        AgentHermesBinding(
            profile_id="support",
            runtime_provider="hermes",
            hermes_node_ids=["h1", "h2"],
            hermes_routing_policy="primary_backup",
        )
    )
    loaded = store.get("support")
    assert loaded.runtime_provider.value == "hermes"
    assert loaded.hermes_node_ids == ["h1", "h2"]
