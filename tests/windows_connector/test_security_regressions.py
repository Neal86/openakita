from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from openakita.windows_connector.executor import (
    ConnectorPermissionError,
    WindowsCommandExecutor,
)
from openakita.windows_connector.manager import WindowsConnectorManager


def test_executor_rejects_ambiguous_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = WindowsCommandExecutor()
    monkeypatch.setattr(
        executor,
        "resources",
        lambda: [
            {"id": "a", "fingerprint": "same"},
            {"id": "b", "fingerprint": "same"},
        ],
    )
    with pytest.raises(ConnectorPermissionError):
        executor._resource("missing", "same")


def test_executor_accepts_unique_stable_identity_after_runtime_id_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = WindowsCommandExecutor()
    grant = {
        "id": "g1",
        "agent_profile_id": "agent",
        "resource_id": "old-id",
        "fingerprint": "old-fingerprint",
        "stable_identity": "stable-app",
        "permissions": {"read": True},
    }
    executor.sync_grants([grant])
    monkeypatch.setattr(
        executor,
        "resources",
        lambda: [
            {
                "id": "new-id",
                "fingerprint": "new-fingerprint",
                "stable_identity": "stable-app",
            }
        ],
    )
    _grant, resource = executor._authorize(
        {
            "grant_id": "g1",
            "agent_profile_id": "agent",
            "resource_id": "new-id",
            "resource_fingerprint": "new-fingerprint",
            "resource_stable_identity": "stable-app",
            "action": "inspect",
        }
    )
    assert resource["id"] == "new-id"


def test_executor_rejects_ambiguous_stable_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = WindowsCommandExecutor()
    executor.sync_grants(
        [
            {
                "id": "g1",
                "agent_profile_id": "agent",
                "resource_id": "old-id",
                "stable_identity": "stable-app",
                "permissions": {"read": True},
            }
        ]
    )
    monkeypatch.setattr(
        executor,
        "resources",
        lambda: [
            {"id": "new-a", "fingerprint": "a", "stable_identity": "stable-app"},
            {"id": "new-b", "fingerprint": "b", "stable_identity": "stable-app"},
        ],
    )
    with pytest.raises(ConnectorPermissionError):
        executor._authorize(
            {
                "grant_id": "g1",
                "agent_profile_id": "agent",
                "resource_id": "new-a",
                "resource_stable_identity": "stable-app",
                "action": "inspect",
            }
        )


def test_uia_title_regex_is_escaped(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class Desktop:
        def __init__(self, backend: str) -> None:
            assert backend == "uia"

        def window(self, **kwargs):
            captured.update(kwargs)
            return object()

    import sys

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=Desktop))
    WindowsCommandExecutor._uia_window({"title": "a[1].*", "hwnd": 0})
    assert captured["title_re"] == r".*a\[1\]\.\*.*"


def test_manager_fingerprint_fallback_requires_unique_live_resource(
    tmp_path: Path,
) -> None:
    manager = WindowsConnectorManager(tmp_path / "state.json")

    async def scenario() -> None:
        await manager.sync_resources(
            "n1",
            [
                {
                    "id": "r1",
                    "fingerprint": "same",
                    "stable_identity": "same",
                    "kind": "app",
                    "app_name": "A",
                },
                {
                    "id": "r2",
                    "fingerprint": "same",
                    "stable_identity": "same",
                    "kind": "app",
                    "app_name": "A",
                },
            ],
        )
        await manager.upsert_grant(
            {"node_id": "n1", "agent_profile_id": "agent", "resource_id": "r1"}
        )
        with pytest.raises(PermissionError):
            await manager._resolve_grant("n1", "agent", "r2", "inspect")

    asyncio.run(scenario())


def test_recovery_does_not_overwrite_good_backup_with_corrupt_primary(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state.json"
    backup = tmp_path / "state.json.bak"
    backup_payload = {
        "version": 4,
        "grants": [],
        "resources": {
            "node": [
                {
                    "id": "r1",
                    "fingerprint": "fp1",
                    "kind": "app",
                    "app_name": "A",
                }
            ]
        },
    }
    backup.write_text(json.dumps(backup_payload), "utf-8")
    state.write_text("{broken", "utf-8")

    manager = WindowsConnectorManager(state)
    assert "r1" in manager._resources["node"]
    manager._save_locked()

    decoded_backup = json.loads(backup.read_text("utf-8"))
    assert decoded_backup == backup_payload
    assert json.loads(state.read_text("utf-8"))["version"] == 4
