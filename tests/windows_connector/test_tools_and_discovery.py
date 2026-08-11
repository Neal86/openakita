from __future__ import annotations

import json

import pytest

from openakita.tools.definitions import get_tool_definition
from openakita.tools.handlers import default_handler_registry
from openakita.windows_connector import app_discovery
from openakita.windows_connector.context import current_agent_profile_id
from openakita.windows_connector.executor import ConnectorPermissionError, WindowsCommandExecutor
from openakita.windows_connector.tools import WindowsConnectorToolHandler


def test_windows_connector_tools_are_in_global_catalog_and_registry() -> None:
    definition = get_tool_definition("windows_list_apps")
    assert definition is not None
    assert definition["category"] == "Windows Connector"
    assert default_handler_registry.has_tool("windows_list_apps")
    assert default_handler_registry.has_tool("windows_browser_click")


def test_discovery_is_safe_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_discovery.os, "name", "posix")
    monkeypatch.setattr(app_discovery, "_cdp_tabs", lambda *_args, **_kwargs: [])
    assert app_discovery.discover_resources() == []


def test_connector_side_rejects_agent_spoof_and_missing_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = WindowsCommandExecutor()
    resource = {
        "id": "tab-1",
        "fingerprint": "fp-1",
        "kind": "browser_tab",
        "app_name": "Google Chrome",
        "process_name": "chrome.exe",
        "pid": 1,
        "hwnd": 2,
        "title": "领星 ERP",
        "exe_path": "C:/Chrome/chrome.exe",
        "account_name": "",
        "browser_profile": "uia",
        "tab_id": "uia:0:领星 ERP",
        "url": "",
        "automation": "uia_tab",
        "controllable": True,
        "limited": True,
    }
    monkeypatch.setattr(executor, "resources", lambda: [resource])
    executor.sync_grants([
        {
            "id": "grant-1",
            "agent_profile_id": "support",
            "resource_id": "tab-1",
            "fingerprint": "fp-1",
            "permissions": {"read": True, "mouse": False, "keyboard": False},
        }
    ])
    with pytest.raises(ConnectorPermissionError):
        executor._authorize({"grant_id": "grant-1", "agent_profile_id": "sales", "resource_id": "tab-1", "resource_fingerprint": "fp-1", "action": "inspect"})
    with pytest.raises(ConnectorPermissionError):
        executor._authorize({"grant_id": "grant-1", "agent_profile_id": "support", "resource_id": "tab-1", "resource_fingerprint": "fp-1", "action": "click"})


@pytest.mark.asyncio
async def test_tool_handler_requires_executor_owned_agent_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = WindowsConnectorToolHandler()
    token = current_agent_profile_id.set("")
    try:
        with pytest.raises(PermissionError):
            await handler.handle("windows_list_apps", {})
    finally:
        current_agent_profile_id.reset(token)


@pytest.mark.asyncio
async def test_list_tool_filters_other_agent_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = WindowsConnectorToolHandler()

    async def nodes():
        return [{"id": "node-1", "name": "客服电脑", "status": "online"}]

    async def resources(_node_id: str):
        return [
            {
                "id": "wechat-a", "kind": "wechat", "app_name": "微信", "title": "微信",
                "account_name": "海外仓客服", "url": "", "automation": "uia", "limited": False,
                "grants": [
                    {"agent_profile_id": "support", "remark": "客服微信", "permissions": {"read": True}},
                    {"agent_profile_id": "sales", "remark": "销售微信", "permissions": {"read": True}},
                ],
            },
            {
                "id": "private", "kind": "browser_tab", "app_name": "Chrome", "title": "银行",
                "account_name": "", "url": "https://bank.example", "automation": "cdp", "limited": False,
                "grants": [{"agent_profile_id": "sales", "remark": "私人", "permissions": {"read": True}}],
            },
        ]

    monkeypatch.setattr("openakita.windows_connector.tools.wechat_desktop_manager.list_nodes", nodes)
    monkeypatch.setattr("openakita.windows_connector.tools.windows_connector_manager.list_resources", resources)
    token = current_agent_profile_id.set("support")
    try:
        result = json.loads(await handler.handle("windows_list_apps", {}))
    finally:
        current_agent_profile_id.reset(token)
    assert [row["resource_id"] for row in result["authorized_resources"]] == ["wechat-a"]
    assert result["authorized_resources"][0]["remark"] == "客服微信"
