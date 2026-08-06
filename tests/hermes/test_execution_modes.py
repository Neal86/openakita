from pathlib import Path

from openakita.hermes.execution import (
    AgentExecutionConfig,
    AgentExecutionStore,
    ExecutionMode,
    HermesInstance,
    HermesInstanceMode,
    HermesInstanceStore,
)
from openakita.hermes.isolation import HermesIsolationManager


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
