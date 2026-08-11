from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "src" / "index.js").read_text("utf-8")
CSS = (ROOT / "dashboard" / "dist" / "style.css").read_text("utf-8")
API = (ROOT / "dashboard" / "plugin_api.py").read_text("utf-8")


def test_management_center_has_complete_tabs_and_states() -> None:
    for tab in ("overview", "agents", "projects", "tasks", "wechat"):
        assert f'"{tab}"' in JS
    assert "projectSupported" in JS
    assert "Native Projects unavailable" in JS
    assert "Loading Management Center" in JS
    assert "No Projects match this view" in JS


def test_agent_ui_exposes_full_management_surface() -> None:
    for label in (
        "Create Agent",
        "Set default",
        "Check gateway",
        "Start",
        "Stop",
        "Restart",
        "Export",
        "Delete",
        "Initial SOUL.md",
        "Create without bundled skills",
    ):
        assert label in JS


def test_project_ui_exposes_native_project_actions() -> None:
    for token in (
        "Create Project",
        "Use project",
        "add_folder",
        "remove_folder",
        "set_primary",
        "assign_agent",
        "Archive",
        "Restore",
    ):
        assert token in JS


def test_task_ui_exposes_edit_and_lifecycle_actions() -> None:
    for token in (
        "Create Task",
        "Run now",
        "Pause",
        "Resume",
        "Delete",
        "Archive",
        "Priority",
        "Deliver",
        "Execution history",
    ):
        assert token in JS


def test_wechat_ui_is_safe_and_observable() -> None:
    for token in (
        "WeChat Desktop",
        "Gateway health",
        "Desktop connection",
        "Unread chats",
        "Recent chats",
        "Safe dry-run test",
        "NO SEND",
        "/wechat/health",
        "/wechat/status",
        "/wechat/dry-run",
    ):
        assert token in JS or token in API


def test_forms_are_real_responsive_dialogs() -> None:
    assert "hx-dialog-backdrop" in JS
    assert "hx-dialog-backdrop" in CSS
    assert "position:fixed" in CSS
    assert "@media(max-width:640px)" in CSS
    assert "height:100vh" in CSS


def test_dashboard_api_exposes_wechat_management_endpoints() -> None:
    for route in ("/wechat/health", "/wechat/status", "/wechat/chats", "/wechat/unread", "/wechat/dry-run"):
        assert route in API
