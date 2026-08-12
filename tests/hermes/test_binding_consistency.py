from pathlib import Path

from openakita.hermes.bindings import AgentHermesBinding, AgentHermesBindingStore
from openakita.hermes.execution import AgentExecutionStore
from openakita.hermes.models import HermesRuntimeProvider


def test_binding_only_reference_is_detectable(tmp_path: Path, monkeypatch):
    from openakita.api.routes import execution_instances as routes

    binding_path = tmp_path / "bindings.json"
    execution_path = tmp_path / "execution.json"
    AgentHermesBindingStore(binding_path).upsert(
        AgentHermesBinding(
            profile_id="customer",
            runtime_provider=HermesRuntimeProvider.HERMES,
            hermes_node_ids=["dedicated-customer"],
        )
    )
    monkeypatch.setattr(routes, "AgentHermesBindingStore", lambda: AgentHermesBindingStore(binding_path))
    monkeypatch.setattr(routes, "AgentExecutionStore", lambda: AgentExecutionStore(execution_path))

    assert routes._bound_profiles("dedicated-customer") == ["customer"]
