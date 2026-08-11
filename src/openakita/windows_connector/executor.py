from __future__ import annotations

import base64
import ctypes
import io
import json
import os
import subprocess
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

    def _select_uia_tab(self, resource: dict[str, Any]) -> None:
        if resource.get("automation") != "uia_tab":
            return
        title = str(resource.get("title") or "").strip()
        if not title:
            return
        window = self._uia_window(resource)
        try:
            window.child_window(title=title, control_type="TabItem").select()
        except Exception:
            window.child_window(title=title, control_type="TabItem").click_input()

    def _inspect(self, resource: dict[str, Any]) -> dict[str, Any]:
        result = dict(resource)
        try:
            self._select_uia_tab(resource)
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
        if resource.get("automation") == "cdp":
            data = self._cdp_command(resource, "Page.captureScreenshot", {"format": "png", "fromSurface": True})
            encoded = str(data.get("data") or "")
            if encoded:
                return {"mime_type": "image/png", "base64": encoded}
        try:
            self._select_uia_tab(resource)
            window = self._uia_window(resource)
            image = window.capture_as_image()
        except Exception:
            from PIL import ImageGrab

            image = ImageGrab.grab(all_screens=True)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return {"mime_type": "image/png", "base64": base64.b64encode(buffer.getvalue()).decode("ascii")}

    def _uia_click(self, resource: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        self._select_uia_tab(resource)
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
        self._select_uia_tab(resource)
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
    def _cdp_target(resource: dict[str, Any]) -> dict[str, Any]:
        profile = str(resource.get("browser_profile") or "")
        if not profile.startswith("cdp:"):
            raise RuntimeError("browser tab does not expose CDP; use its UIA tab resource instead")
        port = int(profile.split(":", 1)[1])
        tab_id = str(resource.get("tab_id") or "")
        request = urllib.request.Request(f"http://127.0.0.1:{port}/json", headers={"User-Agent": "OpenAkita-Windows-Connector/1.0"})
        with urllib.request.urlopen(request, timeout=2) as response:  # noqa: S310 - localhost only
            tabs = json.loads(response.read().decode("utf-8"))
        target = next((item for item in tabs if str(item.get("id") or "") == tab_id), None)
        if target is None or not target.get("webSocketDebuggerUrl"):
            raise RuntimeError("browser tab is no longer available")
        return target

    @classmethod
    def _cdp_command(cls, resource: dict[str, Any], method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        from websockets.sync.client import connect

        target = cls._cdp_target(resource)
        ws_url = str(target["webSocketDebuggerUrl"])
        with connect(ws_url, open_timeout=3, close_timeout=1, max_size=16 * 1024 * 1024) as socket:
            request_id = 1
            socket.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
            while True:
                message = json.loads(socket.recv(timeout=8))
                if message.get("id") != request_id:
                    continue
                if message.get("error"):
                    raise RuntimeError(str(message["error"]))
                return dict(message.get("result") or {})

    @classmethod
    def _cdp_eval(cls, resource: dict[str, Any], expression: str) -> Any:
        result = cls._cdp_command(
            resource,
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True, "userGesture": True},
        )
        remote = result.get("result") or {}
        if remote.get("subtype") == "error":
            raise RuntimeError(str(remote.get("description") or "browser evaluation failed"))
        return remote.get("value")

    @staticmethod
    def _js(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    @classmethod
    def _browser_action(cls, resource: dict[str, Any], action: str, args: dict[str, Any]) -> Any:
        if resource.get("automation") != "cdp":
            # UIA fallback still keeps tabs separately authorized, but cannot
            # safely promise DOM semantics or URL reads.
            if action == "browser_read":
                return {"limited": True, "message": "该 Tab 仅有 UIA 权限；请用 windows_inspect_app 读取可访问控件。"}
            raise RuntimeError("该 Tab 未启用 CDP；可使用 windows_focus/click/type 的 UIA 操作，或开启 Chrome/Edge remote debugging 获得 DOM 控制")
        if action == "browser_read":
            return cls._cdp_eval(resource, "({title:document.title,url:location.href,text:(document.body&&document.body.innerText||'').slice(0,100000)})")
        if action == "browser_navigate":
            url = str(args.get("url") or "").strip()
            if not url:
                raise ValueError("url is required")
            return cls._cdp_command(resource, "Page.navigate", {"url": url})
        if action == "browser_click":
            selector = str(args.get("selector") or "").strip()
            text = str(args.get("text") or "").strip()
            expression = f"""(() => {{
              let el = {('document.querySelector(' + cls._js(selector) + ')') if selector else 'null'};
              if (!el && {cls._js(text)}) {{
                const wanted={cls._js(text)};
                el=[...document.querySelectorAll('button,a,input,[role=button],[role=link],*')].find(x => (x.innerText||x.value||x.getAttribute('aria-label')||'').trim()===wanted);
              }}
              if (!el) return {{ok:false,error:'element not found'}};
              el.scrollIntoView({{block:'center',inline:'center'}}); el.click(); return {{ok:true,tag:el.tagName,text:(el.innerText||el.value||'').slice(0,500)}};
            }})()"""
            result = cls._cdp_eval(resource, expression)
            if isinstance(result, dict) and result.get("ok") is False:
                raise RuntimeError(str(result.get("error")))
            return result
        if action == "browser_type":
            selector = str(args.get("selector") or "").strip()
            text = str(args.get("text") or "")
            if not selector:
                raise ValueError("selector is required")
            expression = f"""(() => {{
              const el=document.querySelector({cls._js(selector)}); if(!el) return {{ok:false,error:'element not found'}};
              el.focus();
              const value={cls._js(text)};
              const proto=el instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
              const setter=Object.getOwnPropertyDescriptor(proto,'value')?.set;
              if(setter) setter.call(el,value); else el.value=value;
              el.dispatchEvent(new Event('input',{{bubbles:true}})); el.dispatchEvent(new Event('change',{{bubbles:true}}));
              return {{ok:true,value:el.value}};
            }})()"""
            result = cls._cdp_eval(resource, expression)
            if isinstance(result, dict) and result.get("ok") is False:
                raise RuntimeError(str(result.get("error")))
            return result
        raise ValueError(f"unsupported browser action: {action}")

    @staticmethod
    def _launch(resource: dict[str, Any]) -> dict[str, Any]:
        exe_path = str(resource.get("exe_path") or "").strip()
        if not exe_path or not os.path.isfile(exe_path):
            raise RuntimeError("该授权资源没有可重新启动的可执行文件路径")
        process = subprocess.Popen([exe_path], close_fds=True)  # noqa: S603 - exact discovered executable only
        return {"launched": exe_path, "pid": process.pid}

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        _grant, resource = self._authorize(payload)
        action = str(payload.get("action") or "")
        args = payload.get("arguments") or {}
        if action in {"inspect", "read_ui"}:
            return {"ok": True, "result": self._inspect(resource)}
        if action == "screenshot":
            return {"ok": True, "result": self._screenshot(resource)}
        if action == "focus":
            self._select_uia_tab(resource)
            self._focus(int(resource.get("hwnd") or 0))
            return {"ok": True, "result": {"focused": resource.get("id")}}
        if action in {"click", "double_click"}:
            if action == "double_click":
                args = {**args, "double": True}
            return {"ok": True, "result": self._uia_click(resource, args)}
        if action == "type":
            return {"ok": True, "result": self._type(resource, args)}
        if action == "hotkey":
            self._select_uia_tab(resource)
            self._focus(int(resource.get("hwnd") or 0))
            from pywinauto.keyboard import send_keys
            send_keys(str(args.get("keys") or ""))
            return {"ok": True, "result": {"sent": args.get("keys")}}
        if action == "scroll":
            self._select_uia_tab(resource)
            from pywinauto import mouse
            mouse.scroll(coords=(int(args.get("x") or 0), int(args.get("y") or 0)), wheel_dist=int(args.get("amount") or -3))
            return {"ok": True, "result": {"scrolled": True}}
        if action.startswith("browser_"):
            return {"ok": True, "result": self._browser_action(resource, action, args)}
        if action == "launch":
            return {"ok": True, "result": self._launch(resource)}
        if action == "close":
            self._select_uia_tab(resource)
            window = self._uia_window(resource)
            window.close()
            return {"ok": True, "result": {"closed": resource.get("id")}}
        raise ValueError(f"unsupported action: {action}")
