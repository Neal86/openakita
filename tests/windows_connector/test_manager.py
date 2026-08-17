from __future__ import annotations

# ruff: noqa: I001

import asyncio
import json
import threading
from pathlib import Path

import pytest

from openakita.windows_connector.manager import (
    LOCAL_NODE_ID,
    WindowsConnectorManager,
)


RESOURCE = {
    "id": "app-1",
    "fingerprint": "stable-app-fingerprint",
    "kind": "wechat",
    "app_name": "微信",
    "process_name": "Weixin.exe",
    "pid": 123,
    "hwnd": 456,
    "title": "微信",
    "exe_path": "C:/Weixin/Weixin.exe",
    "account_name": "海外仓客服",
    "browser_profile": "",
    "tab_id": "",
    "url": "",
    "automation": "uia",
    "controllable": True,
    "limited": False,
}


async def _ignore_send(_node_id: str, _command: dict) -> None:
    return None


@pytest.mark.asyncio
async def test_grant_is_per_agent_and_preserves_remark(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = WindowsConnectorManager(tmp_path / "state.json")
    await manager.sync_resources("node-1", [RESOURCE])
    monkeypatch.setattr("openakita.windows_connector.manager.wechat_desktop_manager.send_command", _ignore_send)
    grant = await manager.upsert_grant(
        {
            "node_id": "node-1",
            "agent_profile_id": "support",
            "resource_id": "app-1",
            "remark": "海外仓客服微信",
            "permissions": {"read": True, "screenshot": True, "mouse": False, "keyboard": False},
        }
    )

    assert grant["remark"] == "海外仓客服微信"
    assert grant["agent_profile_id"] == "support"
    rows = await manager.list_resources("node-1")
    assert rows[0]["account_name"] == "海外仓客服"
    assert rows[0]["grants"][0]["remark"] == "海外仓客服微信"

    with pytest.raises(PermissionError):
        await manager._resolve_grant("node-1", "sales", "app-1", "inspect")
    with pytest.raises(PermissionError):
        await manager._resolve_grant("node-1", "support", "app-1", "click")


@pytest.mark.asyncio
async def test_fingerprint_keeps_grant_when_runtime_resource_id_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = WindowsConnectorManager(tmp_path / "state.json")
    await manager.sync_resources("node-1", [RESOURCE])
    monkeypatch.setattr("openakita.windows_connector.manager.wechat_desktop_manager.send_command", _ignore_send)
    await manager.upsert_grant(
        {
            "node_id": "node-1",
            "agent_profile_id": "support",
            "resource_id": "app-1",
            "permissions": {"read": True},
        }
    )
    restarted = {**RESOURCE, "id": "app-2", "pid": 999, "hwnd": 1000}
    await manager.sync_resources("node-1", [restarted])
    grant, resource = await manager._resolve_grant("node-1", "support", "app-2", "inspect")
    assert grant.fingerprint == "stable-app-fingerprint"
    assert resource.id == "app-2"


@pytest.mark.asyncio
async def test_client_supplied_grant_id_cannot_overwrite_another_grant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = WindowsConnectorManager(tmp_path / "state.json")
    await manager.sync_resources("node-1", [RESOURCE])
    monkeypatch.setattr("openakita.windows_connector.manager.wechat_desktop_manager.send_command", _ignore_send)
    first = await manager.upsert_grant({"node_id": "node-1", "agent_profile_id": "support", "resource_id": "app-1", "permissions": {"read": True}})
    second = await manager.upsert_grant({"id": first["id"], "node_id": "node-1", "agent_profile_id": "sales", "resource_id": "app-1", "permissions": {"read": True}})
    assert second["id"] != first["id"]
    rows = await manager.list_grants("node-1")
    assert {row["agent_profile_id"] for row in rows} == {"support", "sales"}


@pytest.mark.asyncio
async def test_remote_permission_sync_failure_is_visible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = WindowsConnectorManager(tmp_path / "state.json")
    await manager.sync_resources("node-1", [RESOURCE])

    async def fail_send(_node_id: str, _command: dict) -> None:
        raise ConnectionError("offline")

    monkeypatch.setattr("openakita.windows_connector.manager.wechat_desktop_manager.send_command", fail_send)
    grant = await manager.upsert_grant({"node_id": "node-1", "agent_profile_id": "support", "resource_id": "app-1", "permissions": {"read": True}})
    assert grant["sync_state"] == "pending"
    assert "offline" in grant["sync_error"]


def test_corrupt_state_rows_do_not_clear_valid_records(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "version": 4,
                "grants": [
                    {"id": "bad"},
                    {
                        "id": "grant-good",
                        "node_id": "node-1",
                        "agent_profile_id": "support",
                        "resource_id": "app-1",
                        "fingerprint": "stable-app-fingerprint",
                    },
                ],
                "resources": {"node-1": [{"broken": True}, RESOURCE]},
            }
        ),
        "utf-8",
    )
    manager = WindowsConnectorManager(state)
    assert "grant-good" in manager._grants
    assert "bad" not in manager._grants
    assert "app-1" in manager._resources["node-1"]


@pytest.mark.asyncio
async def test_execute_roundtrip_uses_server_side_agent_grant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = WindowsConnectorManager(tmp_path / "state.json")
    await manager.sync_resources("node-1", [RESOURCE])
    monkeypatch.setattr("openakita.windows_connector.manager.wechat_desktop_manager.send_command", _ignore_send)
    grant = await manager.upsert_grant(
        {
            "node_id": "node-1",
            "agent_profile_id": "support",
            "resource_id": "app-1",
            "permissions": {"read": True},
        }
    )

    async def fake_send(node_id: str, command: dict) -> None:
        assert node_id == "node-1"
        assert command["payload"]["agent_profile_id"] == "support"
        assert command["payload"]["grant_id"] == grant["id"]
        asyncio.get_running_loop().call_soon(
            lambda: asyncio.create_task(
                manager.handle_result(
                    node_id,
                    command["request_id"],
                    {"ok": True, "result": {"title": "微信"}},
                )
            )
        )

    monkeypatch.setattr("openakita.windows_connector.manager.wechat_desktop_manager.send_command", fake_send)
    result = await manager.execute(
        node_id="node-1",
        agent_profile_id="support",
        resource_id="app-1",
        action="inspect",
        timeout=2,
    )
    assert result["ok"] is True
    assert result["result"]["title"] == "微信"


@pytest.mark.asyncio
async def test_local_transport_executes_off_event_loop_thread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = WindowsConnectorManager(tmp_path / "state.json")
    monkeypatch.setattr(type(manager), "local_available", property(lambda _self: True))
    monkeypatch.setattr(manager._local_executor, "resources", lambda: [RESOURCE])
    await manager.refresh_local_resources()
    grant = await manager.upsert_grant(
        {
            "node_id": LOCAL_NODE_ID,
            "agent_profile_id": "support",
            "resource_id": "app-1",
            "permissions": {"read": True},
        }
    )
    event_loop_thread = threading.get_ident()

    async def fail_remote_send(_node_id: str, _command: dict) -> None:
        raise AssertionError("local execution must not use remote connector transport")

    async def fake_local_execute(payload: dict) -> dict:
        assert payload["grant_id"] == grant["id"]
        assert payload["agent_profile_id"] == "support"
        assert threading.get_ident() != event_loop_thread
        return {"ok": True, "result": {"transport": "local"}}

    monkeypatch.setattr("openakita.windows_connector.manager.wechat_desktop_manager.send_command", fail_remote_send)
    monkeypatch.setattr(manager._local_executor, "execute", fake_local_execute)

    result = await manager.execute(
        node_id=LOCAL_NODE_ID,
        agent_profile_id="support",
        resource_id="app-1",
        action="inspect",
        timeout=2,
    )
    assert result == {"ok": True, "result": {"transport": "local"}}
    node = await manager.local_node()
    assert node["id"] == LOCAL_NODE_ID
    assert node["transport"] == "local"
    assert node["connector_version"] == "embedded"
