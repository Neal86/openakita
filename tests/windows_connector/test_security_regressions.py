from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from openakita.windows_connector.executor import ConnectorPermissionError, WindowsCommandExecutor
from openakita.windows_connector.manager import WindowsConnectorManager


def test_executor_rejects_ambiguous_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = WindowsCommandExecutor()
    monkeypatch.setattr(executor, "resources", lambda: [
        {"id": "a", "fingerprint": "same"},
        {"id": "b", "fingerprint": "same"},
    ])
    with pytest.raises(ConnectorPermissionError):
        executor._resource("missing", "same")


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


def test_manager_fingerprint_fallback_requires_unique_live_resource(tmp_path: Path) -> None:
    manager = WindowsConnectorManager(tmp_path / "state.json")

    async def scenario() -> None:
        await manager.sync_resources("n1", [
            {"id": "r1", "fingerprint": "same", "stable_identity": "same", "kind": "app", "app_name": "A"},
            {"id": "r2", "fingerprint": "same", "stable_identity": "same", "kind": "app", "app_name": "A"},
        ])
        await manager.upsert_grant({"node_id": "n1", "agent_profile_id": "agent", "resource_id": "r1"})
        with pytest.raises(PermissionError):
            await manager._resolve_grant("n1", "agent", "r2", "inspect")

    asyncio.run(scenario())
