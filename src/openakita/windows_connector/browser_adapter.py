from __future__ import annotations

import asyncio
import base64
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from .manager import windows_connector_manager

logger = logging.getLogger(__name__)

_BROWSER_KINDS = {"browser_profile", "browser_tab"}
_BOUND_LOCKS: dict[str, asyncio.Lock] = {}
_INSTALLED = False


def _binding_key(node_id: str, resource_id: str) -> str:
    return f"{node_id}:{resource_id}"


async def get_browser_binding(agent_profile_id: str) -> dict[str, Any] | None:
    profile_id = str(agent_profile_id or "").strip()
    if not profile_id:
        return None
    grants = await windows_connector_manager.list_grants()
    candidates = [
        grant
        for grant in grants
        if str(grant.get("agent_profile_id") or "") == profile_id
        and str(grant.get("remark") or "") == "browser-binding"
    ]
    for grant in candidates:
        node_id = str(grant.get("node_id") or "")
        resource_id = str(grant.get("resource_id") or "")
        if not node_id or not resource_id:
            continue
        resources = await windows_connector_manager.list_resources(node_id)
        resource = next(
            (row for row in resources if str(row.get("id") or "") == resource_id),
            None,
        )
        if resource and str(resource.get("kind") or "") in _BROWSER_KINDS:
            return {"grant": grant, "resource": resource, "node_id": node_id}
    return None


async def clear_browser_binding(agent_profile_id: str) -> int:
    profile_id = str(agent_profile_id or "").strip()
    if not profile_id:
        return 0
    grants = await windows_connector_manager.list_grants()
    deleted = 0
    for grant in grants:
        if (
            str(grant.get("agent_profile_id") or "") == profile_id
            and str(grant.get("remark") or "") == "browser-binding"
        ):
            grant_id = str(grant.get("id") or "")
            if grant_id and await windows_connector_manager.delete_grant(grant_id):
                deleted += 1
    return deleted


async def set_browser_binding(
    agent_profile_id: str,
    node_id: str,
    resource_id: str,
) -> dict[str, Any]:
    profile_id = str(agent_profile_id or "").strip()
    node = str(node_id or "").strip()
    resource = str(resource_id or "").strip()
    if not profile_id or not node or not resource:
        raise ValueError("agent_profile_id, node_id and resource_id are required")

    resources = await windows_connector_manager.list_resources(node)
    selected = next(
        (row for row in resources if str(row.get("id") or "") == resource),
        None,
    )
    if selected is None:
        raise ValueError("selected browser resource is not currently available")
    if str(selected.get("kind") or "") not in _BROWSER_KINDS:
        raise ValueError("selected Windows resource is not a browser/profile")

    await clear_browser_binding(profile_id)
    grant = await windows_connector_manager.upsert_grant(
        {
            "node_id": node,
            "agent_profile_id": profile_id,
            "resource_id": resource,
            "remark": "browser-binding",
            "permissions": {
                "read": True,
                "screenshot": True,
                "mouse": True,
                "keyboard": True,
                "launch": False,
                "close": False,
            },
        }
    )
    return {"grant": grant, "resource": selected, "node_id": node}


def _browser_upload_definition() -> dict[str, Any]:
    return {
        "name": "browser_upload",
        "category": "Browser",
        "description": (
            "Upload one or more local files through the current browser. Uses the page file input "
            "directly when possible and automatically falls back to the Windows native file picker "
            "for an Agent-bound Windows Connector browser."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector for an <input type=file> or an upload control",
                },
                "path": {"type": "string", "description": "Single local file path"},
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "One or more local file paths",
                },
            },
            "required": ["selector"],
        },
    }


def _paths(params: dict[str, Any]) -> list[str]:
    raw = params.get("paths")
    values = list(raw) if isinstance(raw, list) else []
    if params.get("path"):
        values.insert(0, params.get("path"))
    result = []
    for value in values:
        path = str(value or "").strip()
        if path and path not in result:
            result.append(path)
    return result


def _to_connector_call(tool_name: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    if tool_name == "browser_navigate":
        return "browser_navigate", {"url": params.get("url", "")}
    if tool_name == "browser_get_content":
        return "browser_read", {
            "selector": params.get("selector"),
            "format": params.get("format", "text"),
        }
    if tool_name == "browser_screenshot":
        return "screenshot", {"full_page": bool(params.get("full_page", False))}
    if tool_name == "browser_click":
        return "browser_click", {
            "selector": params.get("selector"),
            "text": params.get("text"),
        }
    if tool_name == "browser_type":
        return "browser_type", {
            "selector": params.get("selector", ""),
            "text": params.get("text", ""),
            "clear_first": params.get("clear", True),
        }
    if tool_name == "browser_scroll":
        amount = int(params.get("amount", 500) or 500)
        if str(params.get("direction", "down")).lower() in {"up", "left"}:
            amount = -abs(amount)
        else:
            amount = abs(amount)
        return "scroll", {"amount": amount, "direction": params.get("direction", "down")}
    if tool_name == "browser_wait":
        return "browser_read", {
            "operation": "wait",
            "selector": params.get("selector"),
            "timeout": params.get("timeout", 30000),
        }
    if tool_name == "browser_execute_js":
        return "browser_type", {"operation": "execute_js", "script": params.get("script", "")}
    if tool_name == "browser_list_tabs":
        return "browser_read", {"operation": "list_tabs"}
    if tool_name == "browser_switch_tab":
        return "browser_click", {"operation": "switch_tab", "index": params.get("index", 0)}
    if tool_name == "browser_new_tab":
        return "browser_navigate", {"operation": "new_tab", "url": params.get("url", "")}
    if tool_name == "browser_close":
        return "browser_click", {"operation": "close_tab"}
    if tool_name == "browser_upload":
        return "browser_type", {
            "operation": "upload",
            "selector": params.get("selector", ""),
            "paths": _paths(params),
        }
    return None


def _format_content(result: Any) -> str:
    if isinstance(result, dict):
        title = str(result.get("title") or "")
        url = str(result.get("url") or "")
        text = result.get("text")
        content = result.get("content")
        if text is not None or content is not None:
            body = text if text is not None else content
            return f"✅ Browser content read\nCurrent URL: {url or 'unknown'}\nTitle: {title or 'unknown'}\n\n{body}"
    return f"✅ {result}"


def _save_screenshot(result: Any) -> str:
    if not isinstance(result, dict):
        return f"✅ {result}"
    encoded = str(result.get("base64") or "")
    if not encoded:
        return f"✅ {result}"
    target = Path(tempfile.gettempdir()) / "openakita-bound-browser.png"
    target.write_bytes(base64.b64decode(encoded))
    return f"✅ Browser screenshot saved: {target}"


async def _handle_bound(handler: Any, tool_name: str, params: dict[str, Any]) -> str | None:
    profile_id = str(getattr(handler.agent, "_agent_profile_id", "") or "").strip()
    binding = await get_browser_binding(profile_id)
    if binding is None:
        return None

    resource = binding["resource"]
    if tool_name == "browser_open":
        return "✅ " + json.dumps(
            {
                "is_open": True,
                "automation_ready": True,
                "status": "bound_windows_connector",
                "connector": binding["node_id"],
                "browser": resource.get("app_name"),
                "profile": resource.get("account_name") or resource.get("browser_profile"),
                "title": resource.get("title"),
                "url": resource.get("url"),
            },
            ensure_ascii=False,
        )

    mapped = _to_connector_call(tool_name, params)
    if mapped is None:
        return f"❌ Bound Windows browser does not support tool: {tool_name}"
    action, arguments = mapped
    lock = _BOUND_LOCKS.setdefault(
        _binding_key(binding["node_id"], str(resource.get("id") or "")), asyncio.Lock()
    )
    try:
        async with lock:
            response = await windows_connector_manager.execute(
                node_id=binding["node_id"],
                agent_profile_id=profile_id,
                resource_id=str(resource.get("id") or ""),
                action=action,
                arguments=arguments,
            )
    except Exception as exc:  # noqa: BLE001 - connector failures are tool results
        logger.warning("Bound browser operation failed: %s", exc)
        return f"❌ Windows Connector browser operation failed: {exc}"

    if not response.get("ok", False):
        return f"❌ {response.get('error') or 'Windows Connector browser operation failed'}"
    result = response.get("result")
    if tool_name == "browser_get_content":
        return _format_content(result)
    if tool_name == "browser_screenshot":
        return _save_screenshot(result)
    return f"✅ {result if result is not None else 'OK'}"


def install_browser_adapter() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    try:
        from openakita.core.policy_v2 import ApprovalClass
        from openakita.tools.definitions.browser import BROWSER_TOOLS
        from openakita.tools.handlers.browser import BrowserHandler
    except Exception as exc:  # pragma: no cover - optional import during bootstrap
        logger.debug("Browser adapter install deferred: %s", exc)
        return

    if not any(str(item.get("name") or "") == "browser_upload" for item in BROWSER_TOOLS):
        BROWSER_TOOLS.append(_browser_upload_definition())
    if "browser_upload" not in BrowserHandler.TOOLS:
        BrowserHandler.TOOLS.append("browser_upload")
    BrowserHandler.TOOL_CLASSES.setdefault("browser_upload", ApprovalClass.EXEC_CAPABLE)

    original = BrowserHandler.handle
    if getattr(original, "_openakita_windows_bound_adapter", False):
        _INSTALLED = True
        return

    async def wrapped(self: Any, tool_name: str, params: dict[str, Any]) -> Any:
        if tool_name != "view_image":
            bound = await _handle_bound(self, tool_name, params)
            if bound is not None:
                return bound
        return await original(self, tool_name, params)

    setattr(wrapped, "_openakita_windows_bound_adapter", True)
    BrowserHandler.handle = wrapped
    _INSTALLED = True
    logger.info("Installed Windows Connector bound-browser adapter")
