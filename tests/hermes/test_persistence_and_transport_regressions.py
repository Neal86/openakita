import json
from pathlib import Path

from openakita.api.routes.agents import VALID_BOT_TYPES
from openakita.hermes.bindings import AgentHermesBindingStore
from openakita.hermes.execution import HermesInstance, HermesInstanceMode
from openakita.hermes.lifecycle import HermesLifecycleService


def test_wechat_desktop_is_supported_by_agent_bot_crud() -> None:
    assert "wechat_desktop" in VALID_BOT_TYPES


def test_explicit_http_hermes_instance_is_not_native_when_windows_defaults_native(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        HermesLifecycleService,
        "native_default",
        staticmethod(lambda: True),
    )
    instance = HermesInstance(
        id="remote-customer-service",
        name="Remote Hermes",
        mode=HermesInstanceMode.DEDICATED,
        container_name="openakita-hermes-remote-customer-service",
        base_url="https://hermes.example.invalid:8642",
    )

    assert HermesLifecycleService.is_native(instance) is False
    assert HermesLifecycleService._should_migrate_default_to_native(instance) is False


def test_legacy_generated_container_url_can_migrate_to_native_default(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        HermesLifecycleService,
        "native_default",
        staticmethod(lambda: True),
    )
    instance = HermesInstance(
        id="legacy",
        name="Legacy",
        mode=HermesInstanceMode.DEDICATED,
        container_name="openakita-hermes-legacy",
        base_url="http://openakita-hermes-legacy:8642",
    )

    assert HermesLifecycleService._should_migrate_default_to_native(instance) is True


def test_binding_store_skips_malformed_rows_without_losing_valid_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bindings.json"
    path.write_text(
        json.dumps(
            {
                "bindings": [
                    {"profile_id": "good", "runtime_provider": "local"},
                    {"profile_id": "bad", "runtime_provider": "not-a-provider"},
                    "not-an-object",
                ]
            }
        ),
        encoding="utf-8",
    )

    rows = AgentHermesBindingStore(path).list()
    assert [row.profile_id for row in rows] == ["good"]
