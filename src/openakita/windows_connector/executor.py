from __future__ import annotations

import base64
import ctypes
import io
import json
import os
import re
import subprocess
import time
import urllib.request
from typing import Any

from .app_discovery import discover_resources


class ConnectorPermissionError(PermissionError):
    pass


class WindowsCommandExecutor:
    _active_tabs: dict[str, str] = {}

    def __init__(self) -> None:
        self._grants: dict[str, dict[str, Any]] = {}

    def sync_grants(self, grants: list[dict[str, Any]]) -> None:
        self._grants = {
            str(item.get("id") or ""): dict(item)
            for item in grants
            if item.get("id")
        }

    def resources(self) -> list[dict[str, Any]]:
        return discover_resources()

    @staticmethod
    def _identity(item: dict[str, Any]) -> str:
        return str(item.get("stable_identity") or item.get("fingerprint") or "")

    def _resource(
        self,
        resource_id: str,
        fingerprint: str = "",
        stable_identity: str = "",
    ) -> dict[str, Any]:
        resources = self.resources()
        for item in resources:
            if str(item.get("id") or "") == resource_id:
                return item
        identity = stable_identity or fingerprint
        if identity:
            matches = [item for item in resources if self._identity(item) == identity]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise ConnectorPermissionError(
                    "resource stable identity is ambiguous; refresh the grant"
                )
        raise RuntimeError("resource is no longer available")

    def _authorize(
        self, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        grant_id = str(payload.get("grant_id") or "")
        agent_id = str(payload.get("agent_profile_id") or "")
        resource_id = str(payload.get("resource_id") or "")
        fingerprint = str(payload.get("resource_fingerprint") or "")
        stable_identity = str(payload.get("resource_stable_identity") or "")
        action = str(payload.get("action") or "")
        grant = self._grants.get(grant_id)
        if not grant or str(grant.get("agent_profile_id") or "") != agent_id:
            raise ConnectorPermissionError("invalid Agent grant")

        grant_resource_id = str(grant.get("resource_id") or "")
        grant_identity = str(
            grant.get("stable_identity") or grant.get("fingerprint") or ""
        )
        requested_identity = stable_identity or fingerprint
        if grant_resource_id != resource_id:
            if not requested_identity or grant_identity != requested_identity:
                raise ConnectorPermissionError("grant does not match requested resource")
            matches = [
                item
                for item in self.resources()
                if self._identity(item) == requested_identity
            ]
            if (
                len(matches) != 1
                or str(matches[0].get("id") or "") != resource_id
            ):
                raise ConnectorPermissionError(
                    "grant fallback identity is ambiguous or stale"
                )

        permissions = grant.get("permissions") or {}
        required = {
            "inspect": "read",
            "read_ui": "read",
            "browser_read": "read",
            "screenshot": "screenshot",
            "focus": "mouse",
            "click": "mouse",
            "double_click": "mouse",
            "scroll": "mouse",
            "browser_click": "mouse",
            "type": "keyboard",
            "hotkey": "keyboard",
            "browser_type": "keyboard",
            "browser_navigate": "keyboard",
            "launch": "launch",
            "close": "close",
        }.get(action)
        if not required or not bool(permissions.get(required, False)):
            raise ConnectorPermissionError(f"grant does not allow action: {action}")
        return grant, self._resource(resource_id, fingerprint, stable_identity)

    @staticmethod
    def _focus(hwnd: int) -> None:
        if os.name != "nt" or not hwnd:
            raise RuntimeError("authorized Windows window is unavailable")
        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd):
            raise RuntimeError("authorized Windows window is no longer available")
        user32.ShowWindow(hwnd, 9)
        if not user32.SetForegroundWindow(hwnd):
            raise RuntimeError("could not focus the authorized Windows window")
        for _ in range(5):
            if int(user32.GetForegroundWindow()) == int(hwnd):
                return
            time.sleep(0.03)
        raise RuntimeError("authorized Windows window did not receive foreground focus")

    @staticmethod
    def _uia_window(resource: dict[str, Any]):
        from pywinauto import Desktop

        hwnd = int(resource.get("hwnd") or 0)
        if hwnd:
            return Desktop(backend="uia").window(handle=hwnd)
        title = str(resource.get("title") or "")
        return Desktop(backend="uia").window(title_re=f".*{re.escape(title)}.*")

    def _select_uia_tab(self, resource: dict[str, Any]) -> None:
        if resource.get("automation") != "uia_tab":
            return
        window = self._uia_window(resource)
        tab_id = str(resource.get("tab_id") or "")
        try:
            index = int(tab_id.split(":", 1)[1]) if tab_id.startswith("uia:") else -1
        except ValueError:
            index = -1
        controls = window.descendants(control_type="TabItem")
        if 0 <= index < len(controls):
            control = controls[index]
            try:
                control.select()
            except Exception:
                control.click_input()
            return
        title = str(resource.get("title") or "").strip()
        if not title:
            raise RuntimeError("authorized UIA tab is no longer available")
        matches = [
            item
            for item in controls
            if str(item.window_text() or "").strip() == title
        ]
        if len(matches) != 1:
            raise ConnectorPermissionError(
                "authorized UIA tab identity is ambiguous or stale"
            )
        try:
            matches[0].select()
        except Exception:
            matches[0].click_input()

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
            data = self._cdp_command(
                resource,
                "Page.captureScreenshot",
                {"format": "png", "fromSurface": True},
            )
            encoded = str(data.get("data") or "")
            if encoded:
                return {"mime_type": "image/png", "base64": encoded}
        try:
            self._select_uia_tab(resource)
            window = self._uia_window(resource)
            image = window.capture_as_image()
        except Exception:
            try:
                window = self._uia_window(resource)
                rect = window.rectangle()
                if rect.width() <= 0 or rect.height() <= 0:
                    raise RuntimeError("authorized window has no capturable area")
                from PIL import ImageGrab

                image = ImageGrab.grab(
                    bbox=(rect.left, rect.top, rect.right, rect.bottom),
                    all_screens=True,
                )
            except Exception as fallback_exc:
                raise RuntimeError("unable to capture only the authorized window") from fallback_exc
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return {
            "mime_type": "image/png",
            "base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
        }

    def _uia_click(self, resource: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        self._select_uia_tab(resource)
        window = self._uia_window(resource)
        target = str(args.get("target") or "").strip()
        if target:
            try:
                control = window.child_window(title=target)
                control.click_input(
                    double=bool(args.get("double", False)),
                    button=str(args.get("button") or "left"),
                )
                return {"clicked": target}
            except Exception:
                pass
        x, y = int(args.get("x") or 0), int(args.get("y") or 0)
        if not x and not y:
            raise ValueError("target or x/y is required")
        rect = window.rectangle()
        if not (rect.left <= x < rect.right and rect.top <= y < rect.bottom):
            raise ConnectorPermissionError("click coordinates are outside the authorized window")
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
    def _cdp_port(resource: dict[str, Any]) -> int:
        profile = str(resource.get("browser_profile") or "")
        if not profile.startswith("cdp:"):
            raise RuntimeError("browser resource does not expose CDP")
        raw = profile.split(":", 2)[1]
        return int(raw)

    @classmethod
    def _profile_key(cls, resource: dict[str, Any]) -> str:
        return f"{cls._cdp_port(resource)}:{resource.get('account_name') or resource.get('browser_profile') or ''}"

    @classmethod
    def _cdp_tabs(cls, resource: dict[str, Any]) -> list[dict[str, Any]]:
        port = cls._cdp_port(resource)
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/json",
            headers={"User-Agent": "OpenAkita-Windows-Connector/1.0"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:  # noqa: S310
            rows = json.loads(response.read().decode("utf-8"))
        return [
            item
            for item in (rows if isinstance(rows, list) else [])
            if isinstance(item, dict)
            and item.get("type") in {"page", "webview"}
            and item.get("webSocketDebuggerUrl")
        ]

    @classmethod
    def _cdp_target(cls, resource: dict[str, Any]) -> dict[str, Any]:
        tabs = cls._cdp_tabs(resource)
        if not tabs:
            raise RuntimeError("browser profile has no controllable tabs")
        key = cls._profile_key(resource)
        requested = cls._active_tabs.get(key) or str(resource.get("tab_id") or "")
        target = next((item for item in tabs if str(item.get("id") or "") == requested), None)
        if target is None:
            target = tabs[0]
            cls._active_tabs[key] = str(target.get("id") or "")
        return target

    @classmethod
    def _cdp_command(
        cls,
        resource: dict[str, Any],
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from websockets.sync.client import connect

        target = cls._cdp_target(resource)
        ws_url = str(target["webSocketDebuggerUrl"])
        with connect(
            ws_url,
            open_timeout=3,
            close_timeout=1,
            max_size=16 * 1024 * 1024,
        ) as socket:
            socket.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
            while True:
                message = json.loads(socket.recv(timeout=8))
                if message.get("id") != 1:
                    continue
                if message.get("error"):
                    raise RuntimeError(str(message["error"]))
                return dict(message.get("result") or {})

    @classmethod
    def _cdp_eval(cls, resource: dict[str, Any], expression: str) -> Any:
        result = cls._cdp_command(
            resource,
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                "userGesture": True,
            },
        )
        remote = result.get("result") or {}
        if remote.get("subtype") == "error":
            raise RuntimeError(str(remote.get("description") or "browser evaluation failed"))
        return remote.get("value")

    @staticmethod
    def _js(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    @classmethod
    def _cdp_upload_input(cls, resource: dict[str, Any], selector: str, paths: list[str]) -> dict[str, Any]:
        from websockets.sync.client import connect

        target = cls._cdp_target(resource)
        with connect(
            str(target["webSocketDebuggerUrl"]),
            open_timeout=3,
            close_timeout=1,
            max_size=16 * 1024 * 1024,
        ) as socket:
            request_id = 0

            def call(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
                nonlocal request_id
                request_id += 1
                socket.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
                while True:
                    message = json.loads(socket.recv(timeout=8))
                    if message.get("id") != request_id:
                        continue
                    if message.get("error"):
                        raise RuntimeError(str(message["error"]))
                    return dict(message.get("result") or {})

            doc = call("DOM.getDocument", {"depth": 1})
            root_id = int((doc.get("root") or {}).get("nodeId") or 0)
            if not root_id:
                raise RuntimeError("unable to read browser DOM")
            found = call("DOM.querySelector", {"nodeId": root_id, "selector": selector})
            node_id = int(found.get("nodeId") or 0)
            if not node_id:
                raise LookupError("file input not found")
            call("DOM.setFileInputFiles", {"nodeId": node_id, "files": paths})
            return {"uploaded": paths, "mode": "dom-file-input"}

    @staticmethod
    def _native_file_picker_upload(paths: list[str]) -> dict[str, Any]:
        if os.name != "nt":
            raise RuntimeError("native file picker fallback is only available on Windows")
        if not paths:
            raise ValueError("at least one upload path is required")
        from pywinauto import Desktop

        deadline = time.monotonic() + 5.0
        dialog = None
        while time.monotonic() < deadline and dialog is None:
            try:
                windows = Desktop(backend="uia").windows()
                for candidate in windows:
                    title = str(candidate.window_text() or "").strip().lower()
                    if any(token in title for token in ("open", "choose", "select", "打开", "选择", "上传")):
                        dialog = candidate
                        break
            except Exception:
                pass
            if dialog is None:
                time.sleep(0.1)
        if dialog is None:
            raise RuntimeError("native Windows file picker did not appear")

        value = " ".join(f'"{path}"' for path in paths)
        edits = dialog.descendants(control_type="Edit")
        if not edits:
            raise RuntimeError("native file picker filename field was not found")
        edit = edits[-1]
        try:
            edit.set_edit_text(value)
        except Exception:
            edit.click_input()
            try:
                import pyperclip
                from pywinauto.keyboard import send_keys

                pyperclip.copy(value)
                send_keys("^a^v")
            except Exception as exc:
                raise RuntimeError("unable to enter upload file path") from exc

        buttons = dialog.descendants(control_type="Button")
        for button in buttons:
            text = str(button.window_text() or "").strip().lower().replace("&", "")
            if text in {"open", "打开", "choose", "select", "选择"}:
                button.click_input()
                return {"uploaded": paths, "mode": "native-file-picker"}
        from pywinauto.keyboard import send_keys

        send_keys("{ENTER}")
        return {"uploaded": paths, "mode": "native-file-picker"}

    @classmethod
    def _browser_action(cls, resource: dict[str, Any], action: str, args: dict[str, Any]) -> Any:
        if resource.get("automation") != "cdp":
            if action == "browser_read":
                return {
                    "limited": True,
                    "message": "该 Tab 仅有 UIA 权限；请用 windows_inspect_app 读取可访问控件。",
                }
            raise RuntimeError(
                "该浏览器未启用 CDP；可使用 Windows Connector UIA 操作，"
                "或开启 Chromium remote debugging 获得完整 Browser Adapter 能力"
            )

        operation = str(args.get("operation") or "").strip()
        if action == "browser_read":
            if operation == "list_tabs":
                tabs = cls._cdp_tabs(resource)
                active = cls._active_tabs.get(cls._profile_key(resource)) or str(resource.get("tab_id") or "")
                return [
                    {
                        "index": index,
                        "id": str(tab.get("id") or ""),
                        "title": str(tab.get("title") or ""),
                        "url": str(tab.get("url") or ""),
                        "active": str(tab.get("id") or "") == active,
                    }
                    for index, tab in enumerate(tabs)
                ]
            if operation == "wait":
                selector = str(args.get("selector") or "").strip()
                timeout_ms = max(0, int(args.get("timeout") or 30000))
                deadline = time.monotonic() + timeout_ms / 1000
                while time.monotonic() <= deadline:
                    if not selector or cls._cdp_eval(resource, f"Boolean(document.querySelector({cls._js(selector)}))"):
                        return {"ready": True, "selector": selector or None}
                    time.sleep(0.1)
                raise TimeoutError(f"browser wait timed out for selector: {selector}")
            selector = str(args.get("selector") or "").strip()
            fmt = str(args.get("format") or "text").lower()
            if selector:
                expression = f"""(() => {{const el=document.querySelector({cls._js(selector)}); if(!el)return {{ok:false,error:'element not found'}}; return {{ok:true,title:document.title,url:location.href,content:{'el.outerHTML' if fmt == 'html' else "(el.innerText||el.textContent||'')"}}};}})()"""
            else:
                expression = "({ok:true,title:document.title,url:location.href,content:" + ("document.documentElement.outerHTML" if fmt == "html" else "(document.body&&document.body.innerText||'')") + "})"
            result = cls._cdp_eval(resource, expression)
            if isinstance(result, dict) and result.get("ok") is False:
                raise RuntimeError(str(result.get("error")))
            if isinstance(result, dict) and "content" in result:
                result["text"] = result.get("content")
            return result

        if action == "browser_navigate":
            url = str(args.get("url") or "").strip()
            if operation == "new_tab":
                port = cls._cdp_port(resource)
                endpoint = f"http://127.0.0.1:{port}/json/new"
                request = urllib.request.Request(endpoint, method="PUT")
                with urllib.request.urlopen(request, timeout=2) as response:  # noqa: S310
                    created = json.loads(response.read().decode("utf-8"))
                tab_id = str(created.get("id") or "")
                if tab_id:
                    cls._active_tabs[cls._profile_key(resource)] = tab_id
                if url:
                    return cls._cdp_command(resource, "Page.navigate", {"url": url})
                return {"created": tab_id}
            if not url:
                raise ValueError("url is required")
            return cls._cdp_command(resource, "Page.navigate", {"url": url})

        if action == "browser_click":
            if operation == "switch_tab":
                tabs = cls._cdp_tabs(resource)
                index = int(args.get("index") or 0)
                if not (0 <= index < len(tabs)):
                    raise IndexError("browser tab index out of range")
                tab_id = str(tabs[index].get("id") or "")
                cls._active_tabs[cls._profile_key(resource)] = tab_id
                cls._cdp_command(resource, "Target.activateTarget", {"targetId": tab_id})
                return {"switched": index, "tab_id": tab_id}
            if operation == "close_tab":
                target = cls._cdp_target(resource)
                tab_id = str(target.get("id") or "")
                result = cls._cdp_command(resource, "Target.closeTarget", {"targetId": tab_id})
                cls._active_tabs.pop(cls._profile_key(resource), None)
                return {"closed": tab_id, **result}
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
            if operation == "execute_js":
                return cls._cdp_eval(resource, str(args.get("script") or ""))
            if operation == "upload":
                paths = [str(value or "").strip() for value in (args.get("paths") or []) if str(value or "").strip()]
                if not paths:
                    raise ValueError("at least one upload path is required")
                missing = [path for path in paths if not os.path.isfile(path)]
                if missing:
                    raise FileNotFoundError(f"upload file not found: {missing[0]}")
                selector = str(args.get("selector") or "").strip()
                if not selector:
                    raise ValueError("selector is required")
                try:
                    return cls._cdp_upload_input(resource, selector, paths)
                except (LookupError, RuntimeError):
                    # The selected control may be an upload button instead of an
                    # input[type=file]. Click it and handle the native Windows picker.
                    click = cls._cdp_eval(
                        resource,
                        f"""(() => {{const el=document.querySelector({cls._js(selector)});if(!el)return false;el.click();return true;}})()""",
                    )
                    if not click:
                        raise RuntimeError("upload control not found")
                    return cls._native_file_picker_upload(paths)
            selector = str(args.get("selector") or "").strip()
            text = str(args.get("text") or "")
            if not selector:
                raise ValueError("selector is required")
            clear_first = bool(args.get("clear_first", True))
            expression = f"""(() => {{
              const el=document.querySelector({cls._js(selector)}); if(!el) return {{ok:false,error:'element not found'}};
              el.focus();
              const incoming={cls._js(text)};
              const clearFirst={str(clear_first).lower()};
              const value=clearFirst?incoming:String(el.value||'')+incoming;
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
        process = subprocess.Popen([exe_path], close_fds=True)  # noqa: S603
        return {"launched": exe_path, "pid": process.pid}

    def _close(self, resource: dict[str, Any]) -> dict[str, Any]:
        if resource.get("automation") == "cdp" and resource.get("kind") == "browser_tab":
            tab_id = str(resource.get("tab_id") or "")
            self._cdp_command(resource, "Target.closeTarget", {"targetId": tab_id})
            return {"closed": resource.get("id"), "scope": "tab"}
        if resource.get("automation") == "uia_tab" and resource.get("kind") == "browser_tab":
            self._select_uia_tab(resource)
            self._focus(int(resource.get("hwnd") or 0))
            from pywinauto.keyboard import send_keys

            send_keys("^w")
            return {"closed": resource.get("id"), "scope": "tab"}
        window = self._uia_window(resource)
        window.close()
        return {"closed": resource.get("id"), "scope": "window"}

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
            if resource.get("automation") == "cdp":
                amount = int(args.get("amount") or 500)
                direction = str(args.get("direction") or "down").lower()
                if direction in {"left", "right"}:
                    x = -abs(amount) if direction == "left" else abs(amount)
                    y = 0
                else:
                    x = 0
                    y = -abs(amount) if direction == "up" else abs(amount)
                result = self._cdp_eval(resource, f"window.scrollBy({x},{y});({{x:window.scrollX,y:window.scrollY}})")
                return {"ok": True, "result": result}
            self._select_uia_tab(resource)
            window = self._uia_window(resource)
            rect = window.rectangle()
            x = int(args.get("x") if args.get("x") is not None else (rect.left + rect.right) // 2)
            y = int(args.get("y") if args.get("y") is not None else (rect.top + rect.bottom) // 2)
            if not (rect.left <= x < rect.right and rect.top <= y < rect.bottom):
                raise ConnectorPermissionError("scroll coordinates are outside the authorized window")
            self._focus(int(resource.get("hwnd") or 0))
            from pywinauto import mouse

            mouse.scroll(coords=(x, y), wheel_dist=int(args.get("amount") or -3))
            return {"ok": True, "result": {"scrolled": True, "coords": [x, y]}}
        if action.startswith("browser_"):
            return {"ok": True, "result": self._browser_action(resource, action, args)}
        if action == "launch":
            return {"ok": True, "result": self._launch(resource)}
        if action == "close":
            return {"ok": True, "result": self._close(resource)}
        raise ValueError(f"unsupported action: {action}")
