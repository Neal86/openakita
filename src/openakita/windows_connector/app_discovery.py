from __future__ import annotations

import ctypes
import hashlib
import json
import os
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
    """Best-effort nickname discovery for multiple WeChat windows.

    wxauto/UIA layouts vary by WeChat version. Prefer a meaningful UIA text
    label and fall back to the top-level title. A user-defined remark remains
    the stable human label when WeChat hides the nickname from accessibility.
    """
    try:
        from pywinauto import Desktop

        window = Desktop(backend="uia").window(handle=hwnd)
        ignored = {"微信", "wechat", "聊天", "通讯录", "收藏", "朋友圈"}
        for child in window.descendants(control_type="Text")[:60]:
            name = str(child.window_text() or "").strip()
            if 1 < len(name) <= 40 and name.lower() not in ignored and not name.isdigit():
                return name
    except Exception:
        pass
    clean = title.replace("- 微信", "").replace("微信", "").strip(" -")
    return clean


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
        if lowered in {"wechat.exe", "weixin.exe"} or "微信" in title:
            kind = "wechat"
            app_name = "微信"
            account_name = _wechat_account_hint(int(hwnd), title)
        elif lowered in {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"}:
            kind = "browser_window"
            app_name = {
                "chrome.exe": "Google Chrome",
                "msedge.exe": "Microsoft Edge",
                "firefox.exe": "Mozilla Firefox",
                "brave.exe": "Brave",
            }.get(lowered, app_name)
            automation = "uia"
            limited = True
        fingerprint = _fingerprint(kind, exe_path or lowered, account_name or title)
        rows.append(
            {
                "id": _resource_id(kind, int(pid.value), int(hwnd), title),
                "fingerprint": fingerprint,
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


def _cdp_tabs(port: int, browser_name: str) -> list[dict[str, Any]]:
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/json",
            headers={"User-Agent": "OpenAkita-Windows-Connector/1.0"},
        )
        with urllib.request.urlopen(request, timeout=0.7) as response:  # noqa: S310 - localhost only
            targets = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for target in targets if isinstance(targets, list) else []:
        if not isinstance(target, dict) or target.get("type") not in {"page", "webview"}:
            continue
        tab_id = str(target.get("id") or "").strip()
        title = str(target.get("title") or target.get("url") or tab_id).strip()
        url = str(target.get("url") or "").strip()
        if not tab_id:
            continue
        fingerprint = _fingerprint("browser_tab", browser_name, url or title)
        rows.append(
            {
                "id": _resource_id("browser_tab", browser_name, port, tab_id),
                "fingerprint": fingerprint,
                "kind": "browser_tab",
                "app_name": browser_name,
                "process_name": "",
                "pid": 0,
                "hwnd": 0,
                "title": title,
                "exe_path": "",
                "account_name": "",
                "browser_profile": f"cdp:{port}",
                "tab_id": tab_id,
                "url": url,
                "automation": "cdp",
                "controllable": True,
                "limited": False,
            }
        )
    return rows


def discover_resources() -> list[dict[str, Any]]:
    """Return visible Windows app instances plus separately addressable browser tabs."""
    rows = _enum_windows()
    cdp_rows: list[dict[str, Any]] = []
    for port in (9222, 9223, 9225, 9333):
        cdp_rows.extend(_cdp_tabs(port, "Chromium Browser"))
    # If CDP identifies tabs, keep browser windows too: windows are useful for
    # focus/screenshot while tab resources provide precise DOM-level identity.
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in [*rows, *cdp_rows]:
        key = str(row.get("id") or "")
        if key and key not in seen:
            seen.add(key)
            result.append(row)
    return result
