from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "wechat" / "adapter.py"
_spec = importlib.util.spec_from_file_location("hx_wechat_adapter_test", ADAPTER_PATH)
assert _spec and _spec.loader
adapter_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = adapter_mod
_spec.loader.exec_module(adapter_mod)
WeChatDesktop = adapter_mod.WeChatDesktop
WeChatUnavailable = adapter_mod.WeChatUnavailable


class FakeEditor:
    def __init__(self) -> None:
        self.clicked = 0

    def click_input(self) -> None:
        self.clicked += 1


def test_status_fails_cleanly_when_not_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(WeChatDesktop, "available", staticmethod(lambda: False))
    result = WeChatDesktop(tmp_path).status()
    assert result["available"] is False


def test_send_refuses_when_target_cannot_be_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = WeChatDesktop(tmp_path)
    fake_window = object()
    monkeypatch.setattr(client, "open_chat", lambda chat: None)
    monkeypatch.setattr(client, "_main_window", lambda: fake_window)
    monkeypatch.setattr(client, "_verify_target", lambda win, chat: False)
    with pytest.raises(WeChatUnavailable):
        client.send_message("Customer Group", "hello")


def test_dry_run_never_sends_enter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = WeChatDesktop(tmp_path)
    fake_window = object()
    editor = FakeEditor()
    keys = []
    monkeypatch.setattr(client, "open_chat", lambda chat: None)
    monkeypatch.setattr(client, "_main_window", lambda: fake_window)
    monkeypatch.setattr(client, "_verify_target", lambda win, chat: True)
    monkeypatch.setattr(client, "_message_editor", lambda win: editor)
    monkeypatch.setattr(client, "_paste", lambda text: None)
    monkeypatch.setattr(client, "_deps", lambda: (None, lambda value, pause=0: keys.append(value), None))
    result = client.send_message("Customer Group", "hello", dry_run=True)
    assert result["dry_run"] is True
    assert "{ENTER}" not in keys
    assert "^a{BACKSPACE}" in keys
    assert editor.clicked == 1


def test_duplicate_send_is_suppressed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = WeChatDesktop(tmp_path)
    fake_window = object()
    editor = FakeEditor()
    keys = []
    monkeypatch.setattr(client, "open_chat", lambda chat: None)
    monkeypatch.setattr(client, "_main_window", lambda: fake_window)
    monkeypatch.setattr(client, "_verify_target", lambda win, chat: True)
    monkeypatch.setattr(client, "_message_editor", lambda win: editor)
    monkeypatch.setattr(client, "_paste", lambda text: None)
    monkeypatch.setattr(client, "_deps", lambda: (None, lambda value, pause=0: keys.append(value), None))
    first = client.send_message("Customer Group", "same reply")
    second = client.send_message("Customer Group", "same reply")
    assert first["sent"] is True
    assert second["duplicate_suppressed"] is True
    assert keys.count("{ENTER}") == 1
