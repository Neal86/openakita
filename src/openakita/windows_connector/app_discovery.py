from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import urllib.request
from ctypes import wintypes
from pathlib import Path
from typing import Any


def _fingerprint(*parts: object) -> str:
    raw = "|".join(str(part or "").strip().lower() for part in parts)
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:24]


def _resource_id(kind: str, *parts: object) -> str:
    return f"{kind}-{_fingerprint(kind, *parts)}"


def _process_info(pid: int) -> tuple[str, str]:
    try:
        import psutil

        process = psutil.Process(pid)
        return process.name(), process.exe()
    except Exception:
        return "", ""


def _wechat_account_hint(hwnd: int, title: str) -> str:
    """Best-effort nickname discovery for separately running WeChat instances."""
    try:
        from pywinauto import Desktop

        window = Desktop(backend="uia").window(handle=hwnd)
        ignored = {"微信", "wechat", "聊天", "通讯录", "收藏", "朋友圈", "小程序"}
        for child in window.descendants(control_type="Text")[:80]:
            name = str(child.window_text() or "").strip()
            if 1 < len(name) <= 40 and name.lower() not in ignored and not name.isdigit():
                return name
    except Exception:
        pass
    return title.replace("- 微信", "").replace("微信", "").strip(" -")


def _browser_name(process_name: str, fallback: str) -> str:
    lowered = process_name.lower()
    if "ixbrowser" in lowered or lowered in {"ix.exe", "ixbrowser.exe"}:
        return "iXBrowser"
    return {
        "chrome.exe": "Google Chrome",
        "msedge.exe": "Microsoft Edge",
        "firefox.exe": "Mozilla Firefox",
        "brave.exe": "Brave",
        "chromium.exe": "Chromium",
    }.get(lowered, fallback)


def _is_browser_process(process_name: str, exe_path: str = "") -> bool:
    haystack = f"{process_name} {exe_path}".lower()
    return any(
        token in haystack
        for token in (
            "chrome.exe",
            "msedge.exe",
            "firefox.exe",
            "brave.exe",
            "chromium.exe",
            "ixbrowser",
        )
    )


def _cmd_value(args: list[str], name: str) -> str:
    prefix = f"{name}="
    for index, raw in enumerate(args):
        value = str(raw or "")
        if value.startswith(prefix):
            return value[len(prefix) :].strip().strip('"')
        if value == name and index + 1 < len(args):
            return str(args[index + 1] or "").strip().strip('"')
    return ""


def _browser_debug_endpoints() -> dict[int, dict[str, Any]]:
    """Discover Chromium-family remote-debugging ports and profile names."""
    if os.name != "nt":
        return {}
    endpoints: dict[int, dict[str, Any]] = {}
    try:
        import psutil

        for process in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
            info = process.info
            process_name = str(info.get("name") or "")
            exe_path = str(info.get("exe") or "")
            if not _is_browser_process(process_name, exe_path):
                continue
            cmdline = [str(value or "") for value in (info.get("cmdline") or [])]
            raw_port = _cmd_value(cmdline, "--remote-debugging-port")
            if not raw_port or not raw_port.isdigit():
                continue
            port = int(raw_port)
            if not (1 <= port <= 65535):
                continue
            profile = _cmd_value(cmdline, "--profile-directory") or "Default"
            user_data_dir = _cmd_value(cmdline, "--user-data-dir")
            browser = _browser_name(process_name, Path(exe_path).stem or "Chromium Browser")
            endpoints.setdefault(
                port,
                {
                    "browser_name": browser,
                    "process_name": process_name,
                    "pid": int(info.get("pid") or 0),
                    "exe_path": exe_path,
                    "profile_name": profile,
                    "user_data_dir": user_data_dir,
                },
            )
    except Exception:
        pass

    # Keep compatibility with manually configured debugging ports even when
    # process cmdline access is denied by Windows policy.
    for port in (9222, 9223, 9225, 9333):
        endpoints.setdefault(
            port,
            {
                "browser_name": "Chromium Browser",
                "process_name": "",
                "pid": 0,
                "exe_path": "",
                "profile_name": "Default",
                "user_data_dir": "",
            },
        )
    return endpoints


def _uia_browser_tabs(window_row: dict[str, Any]) -> list[dict[str, Any]]:
    if os.name != "nt" or window_row.get("kind") != "browser_window":
        return []
    hwnd = int(window_row.get("hwnd") or 0)
    if not hwnd:
        return []
    try:
        from pywinauto import Desktop

        window = Desktop(backend="uia").window(handle=hwnd)
        controls = window.descendants(control_type="TabItem")
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, control in enumerate(controls[:100]):
        try:
            title = str(control.window_text() or "").strip()
            runtime_id = tuple(getattr(control.element_info, "runtime_id", ()) or ())
        except Exception:
            title = ""
            runtime_id = ()
        if not title:
            continue
        tab_locator = _fingerprint(hwnd, runtime_id or index, title)
        if tab_locator in seen:
            continue
        seen.add(tab_locator)
        app_name = str(window_row.get("app_name") or "Browser")
        process_name = str(window_row.get("process_name") or "")
        exe_path = str(window_row.get("exe_path") or "")
        stable_identity = _fingerprint("browser_tab", exe_path or process_name, hwnd, runtime_id or index, title)
        rows.append(
            {
                "id": _resource_id("browser_tab", hwnd, runtime_id or index, title),
                "fingerprint": stable_identity,
                "stable_identity": stable_identity,
                "volatile_window_id": tab_locator,
                "kind": "browser_tab",
                "app_name": app_name,
                "process_name": process_name,
                "pid": int(window_row.get("pid") or 0),
                "hwnd": hwnd,
                "title": title,
                "exe_path": exe_path,
                "account_name": "",
                "browser_profile": "uia",
                "tab_id": f"uia:{index}",
                "url": "",
                "automation": "uia_tab",
                "controllable": True,
                "limited": True,
            }
        )
    return rows


def _enum_windows() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    user32 = ctypes.windll.user32
    rows: list[dict[str, Any]] = []
    enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    @enum_proc_type
    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if not title:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_name, exe_path = _process_info(int(pid.value))
        lowered = process_name.lower()
        app_name = Path(process_name).stem or title
        kind = "app"
        account_name = ""
        automation = "uia"
        limited = False
        if _is_browser_process(process_name, exe_path):
            kind = "browser_window"
            app_name = _browser_name(process_name, app_name)
            limited = True
        elif lowered in {"wechat.exe", "weixin.exe"}:
            kind = "wechat"
            app_name = "微信"
            account_name = _wechat_account_hint(int(hwnd), title)
        if kind == "wechat":
            stable_identity = _fingerprint(kind, exe_path or lowered, account_name or int(hwnd))
        else:
            stable_identity = _fingerprint(kind, exe_path or lowered, title)
        volatile_window_id = _fingerprint(kind, int(pid.value), int(hwnd), title)
        rows.append(
            {
                "id": _resource_id(kind, int(pid.value), int(hwnd), title),
                "fingerprint": stable_identity,
                "stable_identity": stable_identity,
                "volatile_window_id": volatile_window_id,
                "kind": kind,
                "app_name": app_name,
                "process_name": process_name,
                "pid": int(pid.value),
                "hwnd": int(hwnd),
                "title": title,
                "exe_path": exe_path,
                "account_name": account_name,
                "browser_profile": "",
                "tab_id": "",
                "url": "",
                "automation": automation,
                "controllable": True,
                "limited": limited,
            }
        )
        return True

    user32.EnumWindows(callback, 0)
    return rows


def _cdp_targets(port: int, metadata: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/json",
            headers={"User-Agent": "OpenAkita-Windows-Connector/1.0"},
        )
        with urllib.request.urlopen(request, timeout=0.7) as response:  # noqa: S310 - localhost only
            targets = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None, []

    browser_name = str(metadata.get("browser_name") or "Chromium Browser")
    profile_name = str(metadata.get("profile_name") or "Default")
    user_data_dir = str(metadata.get("user_data_dir") or "")
    process_name = str(metadata.get("process_name") or "")
    exe_path = str(metadata.get("exe_path") or "")
    pid = int(metadata.get("pid") or 0)
    page_targets = [
        target
        for target in (targets if isinstance(targets, list) else [])
        if isinstance(target, dict)
        and target.get("type") in {"page", "webview"}
        and target.get("webSocketDebuggerUrl")
    ]
    if not page_targets:
        return None, []

    profile_identity = _fingerprint(
        "browser_profile", browser_name, exe_path or process_name, user_data_dir, profile_name, port
    )
    first = page_targets[0]
    profile_resource = {
        "id": _resource_id("browser_profile", browser_name, user_data_dir, profile_name, port),
        "fingerprint": profile_identity,
        "stable_identity": profile_identity,
        "volatile_window_id": _fingerprint("cdp", port),
        "kind": "browser_profile",
        "app_name": browser_name,
        "process_name": process_name,
        "pid": pid,
        "hwnd": 0,
        "title": f"{browser_name} · {profile_name}",
        "exe_path": exe_path,
        "account_name": profile_name,
        "browser_profile": f"cdp:{port}:{profile_name}",
        "tab_id": str(first.get("id") or ""),
        "url": str(first.get("url") or ""),
        "automation": "cdp",
        "controllable": True,
        "limited": False,
    }

    rows: list[dict[str, Any]] = []
    for target in page_targets:
        tab_id = str(target.get("id") or "").strip()
        title = str(target.get("title") or target.get("url") or tab_id).strip()
        url = str(target.get("url") or "").strip()
        if not tab_id:
            continue
        stable_identity = _fingerprint("browser_tab", browser_name, port, tab_id)
        rows.append(
            {
                "id": _resource_id("browser_tab", browser_name, port, tab_id),
                "fingerprint": stable_identity,
                "stable_identity": stable_identity,
                "volatile_window_id": stable_identity,
                "kind": "browser_tab",
                "app_name": browser_name,
                "process_name": process_name,
                "pid": pid,
                "hwnd": 0,
                "title": title,
                "exe_path": exe_path,
                "account_name": profile_name,
                "browser_profile": f"cdp:{port}:{profile_name}",
                "tab_id": tab_id,
                "url": url,
                "automation": "cdp",
                "controllable": True,
                "limited": False,
            }
        )
    return profile_resource, rows


def discover_resources() -> list[dict[str, Any]]:
    """Return app instances plus separately addressable browser/profile resources."""
    windows = _enum_windows()
    uia_tabs: list[dict[str, Any]] = []
    for window in windows:
        uia_tabs.extend(_uia_browser_tabs(window))

    cdp_profiles: list[dict[str, Any]] = []
    cdp_tabs: list[dict[str, Any]] = []
    for port, metadata in _browser_debug_endpoints().items():
        profile, tabs = _cdp_targets(port, metadata)
        if profile:
            cdp_profiles.append(profile)
            cdp_tabs.extend(tabs)

    cdp_titles = {str(row.get("title") or "").casefold() for row in cdp_tabs if row.get("title")}
    uia_tabs = [row for row in uia_tabs if str(row.get("title") or "").casefold() not in cdp_titles]

    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in [*windows, *cdp_profiles, *cdp_tabs, *uia_tabs]:
        key = str(row.get("id") or "")
        if key and key not in seen:
            seen.add(key)
            result.append(row)
    return result
