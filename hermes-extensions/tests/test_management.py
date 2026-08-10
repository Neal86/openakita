from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = ROOT / "management" / "service.py"
_spec = importlib.util.spec_from_file_location("hx_management_test", SERVICE_PATH)
assert _spec and _spec.loader
service = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(service)
ManagementCenter = service.ManagementCenter


def write_profile(home: Path, *, description: str = "", workspace: str = "") -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "skills").mkdir(exist_ok=True)
    (home / "cron").mkdir(exist_ok=True)
    (home / "cron" / "jobs.json").write_text(json.dumps({"jobs": []}), "utf-8")
    (home / "profile.yaml").write_text(f"description: {description!r}\n", "utf-8")
    (home / "config.yaml").write_text(
        "model:\n  provider: openrouter\n  default: test/model\nterminal:\n  cwd: " + repr(workspace or ".") + "\n",
        "utf-8",
    )


def test_agent_list_reads_native_profile_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_profile(tmp_path, description="Root agent", workspace="/repo/root")
    support = tmp_path / "profiles" / "support"
    write_profile(support, description="Support agent", workspace="/repo/support")
    monkeypatch.setattr(service, "_run", lambda command, **kwargs: "Gateway: running\nSkills: 2")
    center = ManagementCenter(tmp_path)
    rows = center.agent_list()
    assert [row["name"] for row in rows] == ["default", "support"]
    assert rows[1]["description"] == "Support agent"
    assert rows[1]["workspace"] == "/repo/support"
    assert rows[1]["model"] == "test/model"


def test_agent_create_uses_official_profile_and_config_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_profile(tmp_path)
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:3] == ["hermes", "profile", "create"]:
            home = tmp_path / "profiles" / "support"
            write_profile(home, description="Customer support", workspace=".")
            return "created"
        if command[:4] == ["hermes", "profile", "show", "support"]:
            return "Gateway: stopped"
        return "ok"

    monkeypatch.setattr(service, "_run", fake_run)
    center = ManagementCenter(tmp_path)
    center.hermes = "hermes"
    center.agent_create({
        "name": "support",
        "description": "Customer support",
        "clone_mode": "clone",
        "clone_from": "default",
        "workspace": "/work/support",
        "provider": "openrouter",
        "model": "openrouter/test-model",
    })
    assert calls[0] == ["hermes", "profile", "create", "support", "--clone", "--clone-from", "default", "--description", "Customer support"]
    assert ["hermes", "-p", "support", "config", "set", "terminal.cwd", "/work/support"] in calls
    assert ["hermes", "-p", "support", "config", "set", "model.provider", "openrouter"] in calls
    assert ["hermes", "-p", "support", "config", "set", "model.default", "openrouter/test-model"] in calls


def test_agent_delete_protects_default_and_active(tmp_path: Path) -> None:
    write_profile(tmp_path)
    support = tmp_path / "profiles" / "support"
    write_profile(support)
    center = ManagementCenter(tmp_path)
    with pytest.raises(ValueError, match="default profile"):
        center.agent_delete("default")
    (tmp_path / "active_profile").write_text("support", "utf-8")
    with pytest.raises(ValueError, match="active/default-selected"):
        center.agent_delete("support")


def test_soul_write_is_profile_scoped_and_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_profile(tmp_path)
    support = tmp_path / "profiles" / "support"
    write_profile(support)
    monkeypatch.setattr(service, "_run", lambda command, **kwargs: "Gateway: stopped")
    center = ManagementCenter(tmp_path)
    center.agent_update("support", {"soul": "You are support."})
    assert (support / "SOUL.md").read_text("utf-8") == "You are support."
    with pytest.raises(ValueError):
        center.agent_update("../../outside", {"soul": "bad"})


def test_project_list_and_show_parsing() -> None:
    list_text = "* warehouse                Warehouse Ops  [2 folder(s)]\n  old-project              Old Project (archived)  [1 folder(s)]"
    rows = ManagementCenter._parse_project_list(list_text, "default")
    assert rows[0]["active"] is True
    assert rows[0]["slug"] == "warehouse"
    assert rows[1]["archived"] is True
    show = ManagementCenter._parse_project_show(
        "warehouse  [abc123]\n  name:    Warehouse Ops\n  board:   warehouse\n  primary: /repo/main\n  folders:\n    * /repo/main\n      /repo/docs (Docs)",
        "default",
    )
    assert show["primary_path"] == "/repo/main"
    assert show["folders"][0]["is_primary"] is True
    assert show["folders"][1]["label"] == "Docs"


def test_project_create_uses_native_cli_and_assigns_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_profile(tmp_path, workspace=".")
    support = tmp_path / "profiles" / "support"
    write_profile(support, workspace=".")
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if "create" in command and "project" in command:
            return "Created project warehouse (abc123)\nwarehouse  [abc123]\n  name:    Warehouse\n  primary: /repo/warehouse"
        if "show" in command and "project" in command:
            return "warehouse  [abc123]\n  name:    Warehouse\n  primary: /repo/warehouse\n  folders:\n    * /repo/warehouse"
        if command[:4] == ["hermes", "profile", "show", "default"] or command[:4] == ["hermes", "profile", "show", "support"]:
            return "Gateway: stopped"
        return "ok"

    monkeypatch.setattr(service, "_run", fake_run)
    center = ManagementCenter(tmp_path)
    center.hermes = "hermes"
    result = center.project_create({"name": "Warehouse", "primary": "/repo/warehouse", "profile": "default", "agent": "support", "use": True})
    assert result["project"]["slug"] == "warehouse"
    assert ["hermes", "project", "create", "Warehouse", "--primary", "/repo/warehouse", "--use"] in calls
    assert ["hermes", "-p", "support", "config", "set", "terminal.cwd", "/repo/warehouse"] in calls


def test_project_actions_are_profile_scoped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_profile(tmp_path)
    support = tmp_path / "profiles" / "support"
    write_profile(support)
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if "show" in command and "project" in command:
            return "ops  [id1]\n  name:    Ops\n  primary: /repo/ops\n  folders:\n    * /repo/ops"
        if command[:4] == ["hermes", "profile", "show", "default"] or command[:4] == ["hermes", "profile", "show", "support"]:
            return "Gateway: stopped"
        return "ok"

    monkeypatch.setattr(service, "_run", fake_run)
    center = ManagementCenter(tmp_path)
    center.hermes = "hermes"
    center.project_action("ops", "support", "bind_board", "ops-board")
    assert ["hermes", "-p", "support", "project", "bind-board", "ops", "ops-board"] in calls
