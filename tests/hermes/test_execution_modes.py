import json
from pathlib import Path

import pytest

from openakita.hermes import paths as hermes_paths
from openakita.hermes.bindings import AgentHermesBindingStore
from openakita.hermes.execution import (
    AgentExecutionConfig,
    AgentExecutionStore,
    ExecutionMode,
    HermesInstance,
    HermesInstanceMode,
    HermesInstanceStore,
)
from openakita.hermes.isolation import HermesIsolationManager
from openakita.hermes.lifecycle import HermesLifecycleService
from openakita.hermes.models import HermesRuntimeProvider


def test_old_agent_defaults_to_native(tmp_path: Path):
    store = AgentExecutionStore(tmp_path / "execution.json")
    config = store.get("legacy-agent")
    assert config.execution_mode == ExecutionMode.NATIVE
    assert config.hermes_instance_mode == HermesInstanceMode.SHARED


def test_execution_config_roundtrip(tmp_path: Path):
    store = AgentExecutionStore(tmp_path / "execution.json")
    store.upsert(
        AgentExecutionConfig(
            profile_id="customer",
            execution_mode=ExecutionMode.HERMES,
            hermes_instance_mode=HermesInstanceMode.DEDICATED,
            hermes_instance_id="dedicated-customer",
        )
    )
    restored = store.get("customer")
    assert restored.execution_mode == ExecutionMode.HERMES
    assert restored.hermes_instance_id == "dedicated-customer"


@pytest.mark.asyncio
async def test_switching_to_native_clears_previous_hermes_instance_id(
    tmp_path: Path,
    monkeypatch,
):
    binding_path = tmp_path / "bindings.json"
    monkeypatch.setattr(
        "openakita.hermes.lifecycle.AgentHermesBindingStore",
        lambda: AgentHermesBindingStore(binding_path),
    )
    config = AgentExecutionConfig(
        profile_id="customer",
        execution_mode=ExecutionMode.NATIVE,
        hermes_instance_mode=HermesInstanceMode.DEDICATED,
        hermes_instance_id="dedicated-customer",
    )

    normalized, instance = await HermesLifecycleService().apply(config)

    assert instance is None
    assert normalized.hermes_instance_id is None
    binding = AgentHermesBindingStore(binding_path).get("customer")
    assert binding.runtime_provider == HermesRuntimeProvider.LOCAL
    assert binding.hermes_node_ids == []


def test_legacy_native_record_drops_stale_hermes_instance_id(tmp_path: Path):
    path = tmp_path / "execution.json"
    path.write_text(
        json.dumps(
            {
                "agents": [
                    {
                        "profile_id": "customer",
                        "execution_mode": "native",
                        "hermes_instance_mode": "dedicated",
                        "hermes_instance_id": "dedicated-customer",
                    }
                ]
            }
        ),
        "utf-8",
    )

    restored = AgentExecutionStore(path).get("customer")

    assert restored.execution_mode == ExecutionMode.NATIVE
    assert restored.hermes_instance_id is None


def test_execution_store_skips_malformed_rows(tmp_path: Path):
    path = tmp_path / "execution.json"
    path.write_text(
        json.dumps(
            {
                "agents": [
                    {"profile_id": "good", "execution_mode": "native"},
                    {"profile_id": "bad", "execution_mode": "invalid"},
                    {"profile_id": 123, "execution_mode": "native"},
                    "not-an-object",
                ]
            }
        ),
        "utf-8",
    )
    rows = AgentExecutionStore(path).list()
    assert [row.profile_id for row in rows] == ["good"]


def test_instance_store_skips_bad_numeric_fields(tmp_path: Path):
    path = tmp_path / "instances.json"
    path.write_text(
        json.dumps(
            {
                "instances": [
                    {"id": "good", "name": "Good", "mode": "shared"},
                    {
                        "id": "bad",
                        "name": "Bad",
                        "mode": "shared",
                        "max_concurrency": "not-a-number",
                    },
                ]
            }
        ),
        "utf-8",
    )
    rows = HermesInstanceStore(path).list()
    assert [row.id for row in rows] == ["good"]


def test_instances_roundtrip(tmp_path: Path):
    store = HermesInstanceStore(tmp_path / "instances.json")
    instance = HermesInstance(id="shared", name="Shared", mode=HermesInstanceMode.SHARED)
    store.upsert(instance)
    restored = store.get("shared")
    assert restored is not None
    assert restored.container_name == "openakita-hermes-shared"
    assert restored.volume_name.startswith("openakita_hermes_")


def test_shared_profiles_have_separate_roots(tmp_path: Path):
    manager = HermesIsolationManager(tmp_path / "agents")
    first = manager.ensure("customer")
    second = manager.ensure("content")
    assert first["root"] != second["root"]
    Path(first["memory"]).joinpath("private.txt").write_text("customer", "utf-8")
    assert not Path(second["memory"]).joinpath("private.txt").exists()


def test_profile_id_cannot_escape_root(tmp_path: Path):
    manager = HermesIsolationManager(tmp_path / "agents")
    path = manager.profile_root("../../etc/passwd")
    assert manager.root in path.parents


def test_openakita_data_dir_is_used_for_hermes_state(
    tmp_path: Path,
    monkeypatch,
):
    durable = tmp_path / "durable"
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(durable))
    monkeypatch.setattr(hermes_paths, "_project_data_root", lambda: legacy)

    execution = AgentExecutionStore()
    instances = HermesInstanceStore()
    isolation = HermesIsolationManager()

    assert execution._store.path == durable / "agent_execution.json"
    assert instances._store.path == durable / "hermes_instances.json"
    assert isolation.root == (durable / "hermes_agents").resolve()


def test_legacy_hermes_state_is_copied_into_durable_root(
    tmp_path: Path,
    monkeypatch,
):
    durable = tmp_path / "durable"
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "agent_execution.json").write_text(
        json.dumps({"agents": [{"profile_id": "old", "execution_mode": "native"}]}),
        "utf-8",
    )
    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(durable))
    monkeypatch.setattr(hermes_paths, "_project_data_root", lambda: legacy)

    store = AgentExecutionStore()
    assert store.get("old").profile_id == "old"
    assert (durable / "agent_execution.json").exists()
    assert (legacy / "agent_execution.json").exists()
