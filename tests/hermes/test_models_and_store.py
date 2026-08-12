import json
import threading
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


def test_node_store_recovers_from_atomic_backup(tmp_path: Path):
    path = tmp_path / "hermes_nodes.json"
    store = HermesNodeStore(path)
    store.upsert(HermesNode(id="h1", name="One", base_url="http://one:8000"))
    store.upsert(HermesNode(id="h2", name="Two", base_url="http://two:8000"))
    assert path.with_suffix(".json.bak").exists()

    path.write_text("{broken", "utf-8")
    recovered = HermesNodeStore(path).list()
    assert [node.id for node in recovered] == ["h1"]
    assert json.loads(path.read_text("utf-8"))["nodes"][0]["id"] == "h1"


def test_separate_node_store_instances_do_not_lose_updates(tmp_path: Path):
    path = tmp_path / "hermes_nodes.json"
    first = HermesNodeStore(path)
    second = HermesNodeStore(path)
    barrier = threading.Barrier(2)

    def write(store: HermesNodeStore, node_id: str) -> None:
        barrier.wait()
        store.upsert(
            HermesNode(
                id=node_id,
                name=node_id,
                base_url=f"http://{node_id}:8000",
            )
        )

    a = threading.Thread(target=write, args=(first, "h1"))
    b = threading.Thread(target=write, args=(second, "h2"))
    a.start()
    b.start()
    a.join()
    b.join()

    assert {node.id for node in HermesNodeStore(path).list()} == {"h1", "h2"}


def test_node_store_skips_malformed_rows(tmp_path: Path):
    path = tmp_path / "hermes_nodes.json"
    path.write_text(
        json.dumps(
            {
                "nodes": [
                    {"id": "ok", "name": "OK", "base_url": "http://ok:8000"},
                    {"id": "bad", "name": "Bad", "base_url": 123},
                    {
                        "id": "overflow",
                        "name": "Overflow",
                        "base_url": "http://overflow:8000",
                        "max_concurrency": float("inf"),
                    },
                    "not-an-object",
                ]
            }
        ),
        "utf-8",
    )
    rows = HermesNodeStore(path).list()
    assert [node.id for node in rows] == ["ok"]


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


def test_binding_store_skips_bad_rows(tmp_path: Path):
    path = tmp_path / "bindings.json"
    path.write_text(
        json.dumps(
            {
                "bindings": [
                    {"profile_id": "good", "runtime_provider": "local"},
                    {"profile_id": "bad", "runtime_provider": "not-valid"},
                    42,
                ]
            }
        ),
        "utf-8",
    )
    rows = AgentHermesBindingStore(path).list()
    assert [row.profile_id for row in rows] == ["good"]
