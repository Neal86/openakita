from __future__ import annotations

import json
from typing import Any

from openakita.core.policy_v2 import ApprovalClass
from openakita.tools.handlers import default_handler_registry
from openakita.wechat_desktop import wechat_desktop_manager

from .context import current_agent_profile_id
from .manager import windows_connector_manager


def _base_properties() -> dict[str, Any]:
    return {
        "node_id": {"type": "string", "description": "Windows Connector 节点 ID。先调用 windows_list_apps 获取。"},
        "resource_id": {"type": "string", "description": "已授权的应用/微信实例/浏览器 Tab resource_id。"},
    }


WINDOWS_CONNECTOR_TOOLS: list[dict[str, Any]] = [
    {
        "name": "windows_list_apps",
        "category": "Windows Connector",
        "description": "List only the Windows apps, individual WeChat instances/accounts, browser windows and browser tabs explicitly authorized to the current Agent. Use this before any Windows Connector action.",
        "detail": "列出当前 Agent 被明确授权操作的本机资源。不同微信实例和浏览器 Tab 会分别返回，并包含用户备注。未授权资源不会出现在结果中。",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "windows_inspect_app",
        "category": "Windows Connector",
        "description": "Read UI metadata/control tree from one authorized Windows app instance without clicking or typing.",
        "input_schema": {"type": "object", "properties": _base_properties(), "required": ["node_id", "resource_id"]},
    },
    {
        "name": "windows_screenshot_app",
        "category": "Windows Connector",
        "description": "Capture a screenshot of one authorized Windows app or browser tab through its paired Connector.",
        "input_schema": {"type": "object", "properties": _base_properties(), "required": ["node_id", "resource_id"]},
    },
    {
        "name": "windows_focus_app",
        "category": "Windows Connector",
        "description": "Bring one authorized Windows application instance/window to the foreground.",
        "input_schema": {"type": "object", "properties": _base_properties(), "required": ["node_id", "resource_id"]},
    },
    {
        "name": "windows_click_app",
        "category": "Windows Connector",
        "description": "Click inside one authorized Windows app. Prefer a UIA target name; x/y coordinates are fallback.",
        "input_schema": {
            "type": "object",
            "properties": {
                **_base_properties(),
                "target": {"type": "string", "description": "UI element name when available"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                "double": {"type": "boolean", "default": False},
            },
            "required": ["node_id", "resource_id"],
        },
    },
    {
        "name": "windows_type_app",
        "category": "Windows Connector",
        "description": "Type text into the currently focused control of one authorized Windows app.",
        "input_schema": {
            "type": "object",
            "properties": {**_base_properties(), "text": {"type": "string"}, "clear_first": {"type": "boolean", "default": False}},
            "required": ["node_id", "resource_id", "text"],
        },
    },
    {
        "name": "windows_hotkey_app",
        "category": "Windows Connector",
        "description": "Send a keyboard shortcut to one authorized Windows app, for example ^s or %{F4} using pywinauto key syntax.",
        "input_schema": {
            "type": "object",
            "properties": {**_base_properties(), "keys": {"type": "string"}},
            "required": ["node_id", "resource_id", "keys"],
        },
    },
    {
        "name": "windows_scroll_app",
        "category": "Windows Connector",
        "description": "Scroll inside one authorized Windows app/window.",
        "input_schema": {
            "type": "object",
            "properties": {**_base_properties(), "amount": {"type": "integer", "default": -3}, "x": {"type": "integer"}, "y": {"type": "integer"}},
            "required": ["node_id", "resource_id"],
        },
    },
    {
        "name": "windows_browser_read",
        "category": "Windows Connector",
        "description": "Read DOM text from one separately authorized Chrome/Edge browser tab. Requires the tab to expose CDP; otherwise use windows_inspect_app on its browser window resource.",
        "input_schema": {"type": "object", "properties": _base_properties(), "required": ["node_id", "resource_id"]},
    },
    {
        "name": "windows_browser_navigate",
        "category": "Windows Connector",
        "description": "Navigate one separately authorized browser tab to a URL without granting access to other tabs in the same browser.",
        "input_schema": {
            "type": "object",
            "properties": {**_base_properties(), "url": {"type": "string"}},
            "required": ["node_id", "resource_id", "url"],
        },
    },
    {
        "name": "windows_browser_click",
        "category": "Windows Connector",
        "description": "Click a DOM element in one separately authorized browser tab by CSS selector or visible text.",
        "input_schema": {
            "type": "object",
            "properties": {**_base_properties(), "selector": {"type": "string"}, "text": {"type": "string"}},
            "required": ["node_id", "resource_id"],
        },
    },
    {
        "name": "windows_browser_type",
        "category": "Windows Connector",
        "description": "Fill/type text into a DOM element in one separately authorized browser tab.",
        "input_schema": {
            "type": "object",
            "properties": {**_base_properties(), "selector": {"type": "string"}, "text": {"type": "string"}, "clear_first": {"type": "boolean", "default": True}},
            "required": ["node_id", "resource_id", "selector", "text"],
        },
    },
    {
        "name": "windows_close_app",
        "category": "Windows Connector",
        "description": "Close one authorized Windows app/window. This is a side-effecting action and requires the grant's close permission.",
        "input_schema": {"type": "object", "properties": _base_properties(), "required": ["node_id", "resource_id"]},
    },
]


_TOOL_ACTION = {
    "windows_inspect_app": "inspect",
    "windows_screenshot_app": "screenshot",
    "windows_focus_app": "focus",
    "windows_click_app": "click",
    "windows_type_app": "type",
    "windows_hotkey_app": "hotkey",
    "windows_scroll_app": "scroll",
    "windows_browser_read": "browser_read",
    "windows_browser_navigate": "browser_navigate",
    "windows_browser_click": "browser_click",
    "windows_browser_type": "browser_type",
    "windows_close_app": "close",
}


class WindowsConnectorToolHandler:
    TOOLS = [tool["name"] for tool in WINDOWS_CONNECTOR_TOOLS]
    TOOL_CLASSES = {
        "windows_list_apps": ApprovalClass.READONLY_GLOBAL,
        "windows_inspect_app": ApprovalClass.READONLY_GLOBAL,
        "windows_screenshot_app": ApprovalClass.READONLY_GLOBAL,
        "windows_focus_app": ApprovalClass.EXEC_LOW_RISK,
        "windows_click_app": ApprovalClass.EXEC_CAPABLE,
        "windows_type_app": ApprovalClass.EXEC_CAPABLE,
        "windows_hotkey_app": ApprovalClass.EXEC_CAPABLE,
        "windows_scroll_app": ApprovalClass.EXEC_LOW_RISK,
        "windows_browser_read": ApprovalClass.READONLY_GLOBAL,
        "windows_browser_navigate": ApprovalClass.EXEC_CAPABLE,
        "windows_browser_click": ApprovalClass.EXEC_CAPABLE,
        "windows_browser_type": ApprovalClass.EXEC_CAPABLE,
        "windows_close_app": ApprovalClass.EXEC_CAPABLE,
    }

    @staticmethod
    def _agent_id() -> str:
        profile_id = current_agent_profile_id.get("").strip()
        if not profile_id:
            raise PermissionError("Windows Connector tool execution is missing executor-owned Agent identity")
        return profile_id

    async def _list(self, agent_id: str) -> str:
        nodes = await wechat_desktop_manager.list_nodes()
        rows: list[dict[str, Any]] = []
        for node in nodes:
            resources = await windows_connector_manager.list_resources(node["id"])
            for resource in resources:
                matching = [grant for grant in resource.get("grants", []) if grant.get("agent_profile_id") == agent_id]
                if not matching:
                    continue
                rows.append(
                    {
                        "node_id": node["id"],
                        "node_name": node["name"],
                        "node_status": node["status"],
                        "resource_id": resource["id"],
                        "kind": resource.get("kind"),
                        "app_name": resource.get("app_name"),
                        "title": resource.get("title"),
                        "account_name": resource.get("account_name"),
                        "url": resource.get("url"),
                        "automation": resource.get("automation"),
                        "limited": resource.get("limited", False),
                        "remark": matching[0].get("remark", ""),
                        "permissions": matching[0].get("permissions", {}),
                    }
                )
        return json.dumps({"authorized_resources": rows}, ensure_ascii=False)

    async def handle(self, tool_name: str, params: dict[str, Any]) -> str:
        agent_id = self._agent_id()
        if tool_name == "windows_list_apps":
            return await self._list(agent_id)
        action = _TOOL_ACTION.get(tool_name)
        if action is None:
            raise ValueError(f"unsupported Windows Connector tool: {tool_name}")
        node_id = str(params.get("node_id") or "").strip()
        resource_id = str(params.get("resource_id") or "").strip()
        if not node_id or not resource_id:
            raise ValueError("node_id and resource_id are required")
        arguments = {key: value for key, value in params.items() if key not in {"node_id", "resource_id"}}
        result = await windows_connector_manager.execute(
            node_id=node_id,
            agent_profile_id=agent_id,
            resource_id=resource_id,
            action=action,
            arguments=arguments,
        )
        return json.dumps(result, ensure_ascii=False, default=str)


_handler = WindowsConnectorToolHandler()


def register_windows_connector_tools() -> None:
    if default_handler_registry.get_handler("windows_connector") is None:
        default_handler_registry.register(
            "windows_connector",
            _handler.handle,
            tool_names=_handler.TOOLS,
            tool_classes=_handler.TOOL_CLASSES,
        )
