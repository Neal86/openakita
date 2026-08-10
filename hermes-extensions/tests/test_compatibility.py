from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "compatibility.py"
spec = importlib.util.spec_from_file_location("hx_compat_test", PATH)
assert spec and spec.loader
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)


def test_detect_capabilities_handles_missing_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compat.shutil, "which", lambda value: "C:/Hermes/hermes.exe")

    def fake_run(command, **kwargs):
        name = command[1]
        if name == "project":
            return SimpleNamespace(returncode=2, stdout="", stderr="invalid choice: 'project'")
        return SimpleNamespace(returncode=0, stdout=f"usage: hermes {name}", stderr="")

    monkeypatch.setattr(compat.subprocess, "run", fake_run)
    caps = compat.detect_capabilities()
    assert caps.hermes is True
    assert caps.profile is True
    assert caps.dashboard is True
    assert caps.project is False
    assert caps.cron is True
    assert caps.kanban is True


def test_project_unavailable_payload_is_explicit() -> None:
    payload = compat.project_unavailable_payload()
    assert payload["supported"] is False
    assert payload["items"] == []
    assert "hermes project" in payload["message"]
    assert "Agents" in payload["message"]
