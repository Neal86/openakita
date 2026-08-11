from __future__ import annotations

import base64
import ctypes
import io
import json
import os
import urllib.request
from typing import Any

from .app_discovery import discover_resources


class ConnectorPermissionError(PermissionError):
    pass


class WindowsCommandExecutor:
    def __init__(self) -> None:
        self._grants: dict[str, dict[str, Any]] = {}

    def sync_grants(self, grants: list[dict[str, Any]]) -> None:
        self._grants = {str(item.get("id") or ""): dict(item) for item in grants if item.get("id")}

    def resources(self) -> list[dict[str, Any]]:
        return discover_resources()

    def _resource(self, resource_id: str, fingerprint: str = "") -> dict[str, Any]:
        resources = self.resources()
        for item in resources:
            if item.get("id") == resource_id:
                return item
        if fingerprint:
            for item in resources:
                if item.get("fingerprint") == fingerprint:
                    return item
        raise RuntimeError("resource is no longer available")

    def _authorize(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        grant_id = str(payload.get("grant_id") or "")
        agent_id = str(payload.get("agent_profile_id") or "")
        resource_id = str(payload.get("resource_id") or "")
        fingerprint = str(payload.get("resource_fingerprint") or "")
        action = str(payload.get("action") or "")
        grant = self._grants.get(grant_id)
        if not grant or str(grant.get("agent_profile_id") or "") != agent_id:
            raise ConnectorPermissionError("invalid Agent grant")
        if str(grant.get("resource_id") or "") != resource_id and str(grant.get("fingerprint") or "") != fingerprint:
            raise ConnectorPermissionError("grant does not match requested resource")
        permissions = grant.get("permissions") or {}
        required = {
            "inspect": "read", "read_ui": "read", "browser_read": "read",
            "screenshot": "screenshot",
            "focus": "mouse", "click": "mouse", "double_click": "mouse", "scroll": "mouse", "browser_click": "mouse",
            "type": "keyboard", "hotkey": "keyboard", "browser_type": "keyboard", "browser_navigate": "keyboard",
            "launch": "launch", "close": "close",
        }.get(action)
        if not required or not bool(permissions.get(required, False)):
            raise ConnectorPermissionError(f"grant does not allow action: {action}")
        return grant, self._resource(resource_id, fingerprint)

    @staticmethod
    def _focus(hwnd: int) -> None:
        if os.name != "nt" or not hwnd:
            return
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)

    @staticmethod
    def _uia_window(resource: dict[str, Any]):
        from pywinauto import Desktop

        hwnd = int(resource.get("hwnd") or 0)
        if hwnd:
            return Desktop(backend="uia").window(handle=hwnd)
        title = str(resource.get("title") or "")
        return Desktop(backend="uia").window(title_re=f".*{title}.*")

    def _inspect(self, resource: dict[str, Any]) -> dict[str, Any]:
        result = dict(resource)
        try:
            window = self._uia_window(resource)
            result["controls"] = [
                {
                    "name": str(control.window_text() or ""),
                    "type": str(getattr(control.element_info, "control_type", "") or ""),
                    "automation_id": str(getattr(control.element_info, "automation_id", "") or ""),
                }
                for control in window.descendants()[:250]
            ]
        except Exception as exc:
            result["uia_error"] = str(exc)
        return result

    def _screenshot(self, resource: dict[str, Any]) -> dict[str, Any]:
        try:
            window = self._uia_window(resource)
            image = window.capture_as_image()
        except Exception:
            from PIL import ImageGrab

            image = ImageGrab.grab(all_screens=True)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return {"mime_type": "image/png", "base64": base64.b64encode(buffer.getvalue()).decode("ascii")}

    def _uia_click(self, resource: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        window = self._uia_window(resource)
        target = str(args.get("target") or "").strip()
        if target:
            try:
                control = window.child_window(title=target)
                control.click_input(double=bool(args.get("double", False)), button=str(args.get("button") or "left"))
                return {"clicked": target}
            except Exception:
                pass
        x, y = int(args.get("x") or 0), int(args.get("y") or 0)
        if not x and not y:
            raise ValueError("target or x/y is required")
        from pywinauto import mouse

        if bool(args.get("double", False)):
            mouse.double_click(button=str(args.get("button") or "left"), coords=(x, y))
        else:
            mouse.click(button=str(args.get("button") or "left"), coords=(x, y))
        return {"clicked": [x, y]}

    def _type(self, resource: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        self._focus(int(resource.get("hwnd") or 0))
        text = str(args.get("text") or "")
        if args.get("clear_first"):
            from pywinauto.keyboard import send_keys
            send_keys("^a")
        try:
            import pyperclip
            from pywinauto.keyboard import send_keys

            pyperclip.copy(text)
            send_keys("^v")
        except Exception:
            from pywinauto.keyboard import send_keys
            send_keys(text, with_spaces=True)
        return {"typed": len(text)}

    @staticmethod
    def _cdp_call(resource: dict[str, Any], method: str, params: dict[str, Any] | None = None) -> Any:
        profile = str(resource.get("browser_profile") or "")
        if not profile.startswith("cdp:"):
            raise RuntimeError("browser tab does not expose CDP; enable Chrome remote debugging or use UIA")
        port = int(profile.split(":", 1)[1])
        tab_id = str(resource.get("tab_id") or "")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2) as response:  # noqa: S310
            tabs = json.loads(response.read().decode("utf-8"))
        target = next((item for item in tabs if str(item.get("id") or "") == tab_id), None)
        if target is None:
            raise RuntimeError("browser tab is no longer available")
        # Browser DOM commands are delegated to the existing local Playwright/CDP
        # layer when available. The metadata here remains useful even when a
        # browser build exposes only the target list.
        return {"target": target, "method": method, "params": params or {}}

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        _grant, resource = self._authorize(payload)
        action = str(payload.get("action") or "")
        args = payload.get("arguments") or {}
        if action == "inspect" or action == "read_ui":
            return {"ok": True, "result": self._inspect(resource)}
        if action == "screenshot":
            return {"ok": True, "result": self._screenshot(resource)}
        if action == "focus":
            self._focus(int(resource.get("hwnd") or 0))
            return {"ok": True, "result": {"focused": resource.get("id")}}
        if action in {"click", "double_click"}:
            if action == "double_click":
                args = {**args, "double": True}
            return {"ok": True, "result": self._uia_click(resource, args)}
        if action == "type":
            return {"ok": True, "result": self._type(resource, args)}
        if action == "hotkey":
            self._focus(int(resource.get("hwnd") or 0))
            from pywinauto.keyboard import send_keys
            send_keys(str(args.get("keys") or ""))
            return {"ok": True, "result": {"sent": args.get("keys")}}
        if action == "scroll":
            from pywinauto import mouse
            mouse.scroll(coords=(int(args.get("x") or 0), int(args.get("y") or 0)), wheel_dist=int(args.get("amount") or -3))
            return {"ok": True, "result": {"scrolled": True}}
        if action.startswith("browser_"):
            return {"ok": True, "result": self._cdp_call(resource, action, args)}
        if action == "close":
            window = self._uia_window(resource)
            window.close()
            return {"ok": True, "result": {"closed": resource.get("id")}}
        raise ValueError(f"unsupported action: {action}")
