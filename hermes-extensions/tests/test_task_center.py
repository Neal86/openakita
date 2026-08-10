from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = ROOT / "task_center" / "service.py"
_spec = importlib.util.spec_from_file_location("hx_task_service_test", SERVICE_PATH)
assert _spec and _spec.loader
service = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(service)
TaskCenter = service.TaskCenter


def write_jobs(home: Path, jobs: list[dict]) -> None:
    path = home / "cron" / "jobs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"jobs": jobs}), "utf-8")


def test_profiles_and_cron_are_aggregated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    support = tmp_path / "profiles" / "support"
    support.mkdir(parents=True)
    write_jobs(tmp_path, [{"id": "d1", "name": "default-job", "schedule": {"kind": "interval", "minutes": 60}, "next_run_at": "2030-01-01T00:00:00Z"}])
    write_jobs(support, [{"id": "s1", "name": "support-job", "schedule": {"kind": "cron", "expr": "0 9 * * *"}, "next_run_at": "2030-01-01T09:00:00Z"}])
    monkeypatch.setattr(TaskCenter, "kanban_tasks", lambda self, profile=None, include_completed=False: [])

    center = TaskCenter(tmp_path)
    overview = center.overview()
    assert [p["name"] for p in overview["profiles"]] == ["default", "support"]
    assert overview["counts"]["cron"] == 2
    assert overview["counts"]["recurring"] == 2
    jobs = center.cron_jobs()
    assert jobs[0]["schedule"] == "every 1h"
    assert jobs[1]["schedule"] == "0 9 * * *"


def test_structured_interval_is_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    start = datetime.now(UTC) + timedelta(minutes=5)
    write_jobs(tmp_path, [{
        "id": "j1",
        "name": "check inbox",
        "schedule": {"kind": "interval", "minutes": 60},
        "next_run_at": start.isoformat(),
    }])
    monkeypatch.setattr(TaskCenter, "kanban_tasks", lambda self, profile=None, include_completed=False: [])
    rows = TaskCenter(tmp_path).upcoming(hours=4, limit=20)
    assert len(rows) >= 3
    assert all(row["id"] == "j1" for row in rows)
    times = [datetime.fromisoformat(row["at"]) for row in rows]
    assert times == sorted(times)
    assert times[1] - times[0] == timedelta(hours=1)


def test_structured_once_is_not_recurring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    start = datetime.now(UTC) + timedelta(hours=2)
    write_jobs(tmp_path, [{
        "id": "j2",
        "name": "one shot",
        "schedule": {"kind": "once", "run_at": start.isoformat()},
        "next_run_at": start.isoformat(),
    }])
    monkeypatch.setattr(TaskCenter, "kanban_tasks", lambda self, profile=None, include_completed=False: [])
    center = TaskCenter(tmp_path)
    job = center.cron_jobs()[0]
    assert job["recurring"] is False
    assert center.overview()["counts"]["one_shot"] == 1
    assert len(center.upcoming(hours=4)) == 1


def test_nondefault_cron_create_uses_global_profile_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "profiles" / "support").mkdir(parents=True)
    calls = []

    def fake(command, env=None):
        calls.append((command, env))
        return "created"

    monkeypatch.setattr(service, "_plain_output", fake)
    center = TaskCenter(tmp_path)
    center.hermes = "hermes"
    result = center.create({
        "type": "cron",
        "name": "support sweep",
        "prompt": "Check messages",
        "schedule": "every 10m",
        "profile": "support",
    })
    assert result["profile"] == "support"
    assert calls[0][0][:4] == ["hermes", "-p", "support", "cron"]
    assert "--profile" not in calls[0][0]


def test_nondefault_cron_action_is_profile_scoped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "profiles" / "support").mkdir(parents=True)
    calls = []
    monkeypatch.setattr(service, "_plain_output", lambda command, env=None: calls.append(command) or "ok")
    center = TaskCenter(tmp_path)
    center.hermes = "hermes"
    center.action({"type": "cron", "id": "job-1", "action": "pause", "profile": "support"})
    assert calls == [["hermes", "-p", "support", "cron", "pause", "job-1"]]


def test_profile_path_escape_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "profiles").mkdir(parents=True)
    center = TaskCenter(tmp_path)
    with pytest.raises(ValueError):
        center._profile_home("../../outside")
