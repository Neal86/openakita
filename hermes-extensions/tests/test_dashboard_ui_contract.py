from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "dashboard" / "src"
JS = "\n".join((SRC / name).read_text("utf-8") for name in ("api.js", "components.js", "app.js", "index.js"))
CSS = (ROOT / "dashboard" / "dist" / "style.css").read_text("utf-8")
API = (ROOT / "dashboard" / "plugin_api.py").read_text("utf-8")
BUILD = (ROOT / "dashboard" / "build_bundle.py").read_text("utf-8")


def test_dashboard_source_is_modular_but_release_is_single_bundle() -> None:
    for name in ("api.js", "components.js", "app.js", "index.js"):
        assert (SRC / name).is_file()
    assert 'ORDER = ["api.js", "components.js", "app.js", "index.js"]' in BUILD
    assert 'dist" / "index.js"' in BUILD


def test_management_center_has_complete_tabs_and_states() -> None:
    for tab in ("overview", "agents", "projects", "tasks", "wechat"):
        assert f'"{tab}"' in JS
    assert "projectSupported" in JS
    assert "Native Projects unavailable" in JS
    assert "Loading Management Center" in JS


def test_agent_project_task_management_surfaces_remain_complete() -> None:
    for token in (
        "Create Agent", "Set default", "Check gateway", "Restart", "Export", "Delete Agent",
        "Create Project", "Use project", "add_folder", "remove_folder", "set_primary", "assign_agent",
        "Create Task", "Run now", "Pause", "Resume", "Delete Task", "Archive Task", "Priority", "Deliver", "Execution history",
    ):
        assert token in JS


def test_wechat_tab_never_auto_scans_desktop() -> None:
    assert 'if (tab === "wechat") loadHealth()' in JS
    assert 'if (tab === "wechat") loadWeChat(true)' not in JS
    assert "checkWeChatDesktop" in JS
    assert "Promise.allSettled" in JS
    assert "Partial desktop results" in JS
    assert "Opening this tab does not touch the desktop app" in JS


def test_refresh_is_context_aware_and_auto_refresh_is_visibility_guarded() -> None:
    assert "refreshCurrent" in JS
    assert 'if (tab === "tasks")' in JS
    assert 'if (tab === "wechat")' in JS
    assert 'document.visibilityState !== "visible"' in JS
    assert "15000" in JS and "30000" in JS


def test_dialogs_are_accessible_and_protect_unsaved_changes() -> None:
    assert "focusables" in JS
    assert 'e.key === "Tab"' in JS
    assert "previousFocus" in JS
    assert "Discard unsaved changes?" in JS
    assert "ConfirmDialog" in JS
    assert "guardedClose" in JS
    assert "confirm(" not in JS


def test_mobile_and_focus_styles_are_touch_friendly() -> None:
    assert "hx-dialog-backdrop" in CSS
    assert "@media(max-width:640px)" in CSS
    assert "min-height:44px" in CSS
    assert ":focus-visible" in CSS
    assert ".hx-actions{flex-wrap:wrap}" in CSS


def test_dashboard_api_exposes_wechat_management_endpoints() -> None:
    for route in ("/wechat/health", "/wechat/status", "/wechat/chats", "/wechat/unread", "/wechat/dry-run"):
        assert route in API
