from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), UTC).isoformat()
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC).isoformat()
    except Exception:
        return text


def _as_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), UTC)
        except Exception:
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except Exception:
        return None


def _json_output(command: list[str], env: dict[str, str] | None = None) -> Any:
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "Hermes command failed").strip())
    text = proc.stdout.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Hermes command did not return JSON: {text[:500]}") from exc


def _plain_output(command: list[str], env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(command, capture_output=True, text=True, timeout=60, env=env, check=False)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "Hermes command failed").strip())
    return proc.stdout.strip()


class TaskCenter:
    """Read fleet state directly; mutate schedules only through Hermes native CLI."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path.home() / ".hermes").expanduser().resolve()
        self.hermes = shutil.which("hermes") or "hermes"

    def profiles(self) -> list[dict[str, str]]:
        rows = [{"name": "default", "home": str(self.root)}]
        profiles_root = self.root / "profiles"
        if profiles_root.is_dir():
            for path in sorted(profiles_root.iterdir(), key=lambda p: p.name.lower()):
                if path.is_dir() and not path.name.startswith("."):
                    rows.append({"name": path.name, "home": str(path.resolve())})
        return rows

    def _profile_home(self, profile: str | None) -> Path:
        if not profile or profile == "default":
            return self.root
        path = (self.root / "profiles" / profile).resolve()
        profiles_root = (self.root / "profiles").resolve()
        if profiles_root not in path.parents or not path.is_dir():
            raise ValueError(f"Unknown Hermes profile: {profile}")
        return path

    def _env_for(self, profile: str | None) -> dict[str, str]:
        env = os.environ.copy()
        env["HERMES_HOME"] = str(self._profile_home(profile))
        return env

    def _cron_jobs(self, profile: str) -> list[dict[str, Any]]:
        home = self._profile_home(profile)
        path = home / "cron" / "jobs.json"
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        jobs = payload.get("jobs", payload if isinstance(payload, list) else [])
        result: list[dict[str, Any]] = []
        for job in jobs if isinstance(jobs, list) else []:
            if not isinstance(job, dict):
                continue
            row = dict(job)
            row["profile"] = profile
            row["type"] = "cron"
            row["id"] = str(row.get("id") or row.get("job_id") or row.get("name") or "")
            row["name"] = str(row.get("name") or row.get("id") or "Untitled cron job")
            row["schedule"] = row.get("schedule") or row.get("cron") or row.get("when")
            row["next_run_at"] = _iso(row.get("next_run_at") or row.get("next_run"))
            row["last_run_at"] = _iso(row.get("last_run_at") or row.get("last_run"))
            row["enabled"] = not bool(row.get("paused")) and row.get("enabled", True) is not False
            result.append(row)
        return result

    def cron_jobs(self, profile: str | None = None) -> list[dict[str, Any]]:
        names = [profile] if profile else [item["name"] for item in self.profiles()]
        rows: list[dict[str, Any]] = []
        for name in names:
            if name:
                rows.extend(self._cron_jobs(name))
        return rows

    def _cron_history(self, profile: str, job_id: str, limit: int) -> list[dict[str, Any]]:
        db_path = self._profile_home(profile) / "cron" / "executions.db"
        if not db_path.exists():
            return []
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            candidates = [name for name in ("executions", "runs", "attempts") if name in tables]
            if not candidates:
                return []
            table = candidates[0]
            columns = [row[1] for row in con.execute(f"PRAGMA table_info({table})")]
            job_col = next((c for c in ("job_id", "cron_job_id", "task_id") if c in columns), None)
            order_col = next((c for c in ("started_at", "claimed_at", "created_at", "id") if c in columns), None)
            where = f" WHERE {job_col} = ?" if job_col else ""
            order = f" ORDER BY {order_col} DESC" if order_col else ""
            params: tuple[Any, ...] = (job_id,) if job_col else ()
            query = f"SELECT * FROM {table}{where}{order} LIMIT ?"
            rows = [dict(row) for row in con.execute(query, (*params, max(1, min(limit, 200))))]
            for row in rows:
                row["profile"] = profile
                row["type"] = "cron_run"
            return rows
        finally:
            con.close()

    def _kanban(self, args: list[str]) -> Any:
        return _json_output([self.hermes, "kanban", *args, "--json"])

    def kanban_tasks(self, profile: str | None = None, include_completed: bool = False) -> list[dict[str, Any]]:
        args = ["list"]
        if profile:
            args += ["--assignee", profile]
        if not include_completed:
            # Hermes treats omitted status as all active board rows; filter terminal rows below for forward compatibility.
            pass
        payload = self._kanban(args)
        rows = payload.get("tasks", payload) if isinstance(payload, dict) else payload
        result: list[dict[str, Any]] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            status = str(item.get("status") or "")
            if not include_completed and status in {"done", "completed", "archived", "cancelled"}:
                continue
            item["type"] = "kanban"
            item["profile"] = str(item.get("assignee") or "")
            item["id"] = str(item.get("id") or item.get("task_id") or "")
            item["name"] = str(item.get("title") or item.get("name") or item["id"])
            item["next_run_at"] = _iso(item.get("scheduled_at"))
            result.append(item)
        return result

    def overview(self, profile: str | None = None, include_completed: bool = False) -> dict[str, Any]:
        cron = self.cron_jobs(profile)
        try:
            kanban = self.kanban_tasks(profile, include_completed=include_completed)
            kanban_error = None
        except Exception as exc:
            kanban = []
            kanban_error = str(exc)
        profile_rows = self.profiles()
        if profile:
            profile_rows = [p for p in profile_rows if p["name"] == profile]
        grouped: dict[str, dict[str, Any]] = {}
        for item in profile_rows:
            grouped[item["name"]] = {**item, "cron": [], "kanban": []}
        for item in cron:
            grouped.setdefault(item["profile"], {"name": item["profile"], "home": "", "cron": [], "kanban": []})["cron"].append(item)
        for item in kanban:
            key = item.get("profile") or "unassigned"
            grouped.setdefault(key, {"name": key, "home": "", "cron": [], "kanban": []})["kanban"].append(item)
        return {
            "profiles": list(grouped.values()),
            "counts": {
                "profiles": len(profile_rows),
                "cron": len(cron),
                "recurring": sum(1 for j in cron if self._is_recurring(j.get("schedule"))),
                "one_shot": sum(1 for j in cron if not self._is_recurring(j.get("schedule"))),
                "kanban": len(kanban),
            },
            "kanban_error": kanban_error,
            "generated_at": _now().isoformat(),
        }

    @staticmethod
    def _is_recurring(schedule: Any) -> bool:
        text = str(schedule or "").strip().lower()
        if not text:
            return False
        if text.startswith("every "):
            return True
        return len(text.split()) == 5

    def upcoming(self, hours: int = 24 * 7, profile: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        horizon = _now() + timedelta(hours=max(1, min(hours, 24 * 90)))
        rows: list[dict[str, Any]] = []
        for job in self.cron_jobs(profile):
            next_dt = _as_dt(job.get("next_run_at"))
            if next_dt and next_dt <= horizon and job.get("enabled", True):
                rows.append({
                    "type": "cron",
                    "id": job["id"],
                    "name": job["name"],
                    "profile": job["profile"],
                    "at": next_dt.isoformat(),
                    "schedule": job.get("schedule"),
                    "recurring": self._is_recurring(job.get("schedule")),
                })
                rows.extend(self._expand_recurrence(job, next_dt, horizon, max(0, min(limit, 1000) - len(rows))))
        try:
            for task in self.kanban_tasks(profile, include_completed=False):
                dt = _as_dt(task.get("next_run_at"))
                if dt and _now() <= dt <= horizon:
                    rows.append({
                        "type": "kanban",
                        "id": task["id"],
                        "name": task["name"],
                        "profile": task.get("profile") or "",
                        "at": dt.isoformat(),
                        "schedule": None,
                        "recurring": False,
                    })
        except Exception:
            pass
        rows.sort(key=lambda item: item.get("at") or "")
        return rows[: max(1, min(limit, 1000))]

    def _expand_recurrence(self, job: dict[str, Any], first: datetime, horizon: datetime, remaining: int) -> list[dict[str, Any]]:
        if remaining <= 0 or not self._is_recurring(job.get("schedule")):
            return []
        schedule = str(job.get("schedule") or "").strip()
        result: list[dict[str, Any]] = []
        try:
            from croniter import croniter  # type: ignore
        except Exception:
            croniter = None
        if schedule.lower().startswith("every "):
            interval = schedule[6:].strip().lower()
            multiplier = 1
            if interval.endswith("m"):
                step = timedelta(minutes=float(interval[:-1]))
            elif interval.endswith("h"):
                step = timedelta(hours=float(interval[:-1]))
            elif interval.endswith("d"):
                step = timedelta(days=float(interval[:-1]))
            else:
                return []
            cursor = first
            while len(result) < remaining:
                cursor += step * multiplier
                if cursor > horizon:
                    break
                result.append(self._upcoming_copy(job, cursor))
            return result
        if croniter is None:
            return []
        try:
            iterator = croniter(schedule, first)
            while len(result) < remaining:
                cursor = iterator.get_next(datetime)
                if cursor.tzinfo is None:
                    cursor = cursor.replace(tzinfo=UTC)
                cursor = cursor.astimezone(UTC)
                if cursor > horizon:
                    break
                result.append(self._upcoming_copy(job, cursor))
        except Exception:
            return []
        return result

    @staticmethod
    def _upcoming_copy(job: dict[str, Any], at: datetime) -> dict[str, Any]:
        return {
            "type": "cron",
            "id": job["id"],
            "name": job["name"],
            "profile": job["profile"],
            "at": at.isoformat(),
            "schedule": job.get("schedule"),
            "recurring": True,
        }

    def create(self, args: dict[str, Any]) -> dict[str, Any]:
        task_type = str(args.get("type") or "")
        name = str(args.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")
        if task_type == "cron":
            schedule = str(args.get("schedule") or "").strip()
            prompt = str(args.get("prompt") or "").strip()
            if not schedule or not prompt:
                raise ValueError("cron tasks require schedule and prompt")
            command = [self.hermes, "cron", "create", schedule, prompt, "--name", name]
            profile = str(args.get("profile") or "").strip()
            if profile and profile != "default":
                command += ["--profile", profile]
            deliver = str(args.get("deliver") or "").strip()
            if deliver:
                command += ["--deliver", deliver]
            output = _plain_output(command, self._env_for(profile or None))
            return {"ok": True, "type": "cron", "output": output}
        if task_type == "kanban":
            command = [self.hermes, "kanban", "create", name]
            body = str(args.get("prompt") or "").strip()
            if body:
                command += ["--body", body]
            profile = str(args.get("profile") or "").strip()
            if profile:
                command += ["--assignee", profile]
            if args.get("priority") is not None:
                command += ["--priority", str(int(args["priority"]))]
            payload = _json_output([*command, "--json"])
            return {"ok": True, "type": "kanban", "task": payload}
        raise ValueError("type must be cron or kanban")

    def update(self, args: dict[str, Any]) -> dict[str, Any]:
        task_type = str(args.get("type") or "")
        task_id = str(args.get("id") or "").strip()
        if not task_id:
            raise ValueError("id is required")
        if task_type == "cron":
            command = [self.hermes, "cron", "edit", task_id]
            if args.get("schedule") is not None:
                command += ["--schedule", str(args["schedule"])]
            if args.get("prompt") is not None:
                command += ["--prompt", str(args["prompt"])]
            if args.get("name") is not None:
                command += ["--name", str(args["name"])]
            profile = str(args.get("profile") or "").strip()
            if profile:
                command += ["--profile", profile]
            if len(command) == 4:
                raise ValueError("no cron fields supplied")
            return {"ok": True, "type": "cron", "output": _plain_output(command, self._env_for(profile or None))}
        if task_type == "kanban":
            command = [self.hermes, "kanban", "edit", task_id]
            if args.get("name") is not None:
                command += ["--title", str(args["name"])]
            if args.get("prompt") is not None:
                command += ["--body", str(args["prompt"])]
            if args.get("priority") is not None:
                command += ["--priority", str(int(args["priority"]))]
            if len(command) == 4:
                raise ValueError("no Kanban fields supplied")
            output = _plain_output(command)
            profile = str(args.get("profile") or "").strip()
            if profile:
                _plain_output([self.hermes, "kanban", "assign", task_id, profile])
            return {"ok": True, "type": "kanban", "output": output}
        raise ValueError("type must be cron or kanban")

    def action(self, args: dict[str, Any]) -> dict[str, Any]:
        task_type = str(args.get("type") or "")
        task_id = str(args.get("id") or "").strip()
        action = str(args.get("action") or "").strip()
        value = str(args.get("value") or "").strip()
        if not task_id or not action:
            raise ValueError("id and action are required")
        if task_type == "cron":
            if action not in {"pause", "resume", "run", "remove"}:
                raise ValueError("unsupported cron action")
            return {"ok": True, "type": "cron", "output": _plain_output([self.hermes, "cron", action, task_id])}
        if task_type == "kanban":
            if action == "assign":
                if not value:
                    raise ValueError("assign requires value")
                command = [self.hermes, "kanban", "assign", task_id, value]
            elif action == "archive":
                command = [self.hermes, "kanban", "archive", task_id]
            elif action == "schedule":
                if not value:
                    raise ValueError("schedule requires ISO8601 value")
                command = [self.hermes, "kanban", "schedule", task_id, "--at", value]
            else:
                raise ValueError("unsupported Kanban action")
            return {"ok": True, "type": "kanban", "output": _plain_output(command)}
        raise ValueError("type must be cron or kanban")

    def history(self, task_type: str, task_id: str, limit: int = 20, profile: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        if task_type == "cron":
            if profile:
                return self._cron_history(profile, task_id, limit)
            rows: list[dict[str, Any]] = []
            for p in self.profiles():
                rows.extend(self._cron_history(p["name"], task_id, limit))
            return rows[:limit]
        if task_type == "kanban":
            payload = _json_output([self.hermes, "kanban", "runs", task_id, "--limit", str(limit), "--json"])
            rows = payload.get("runs", payload) if isinstance(payload, dict) else payload
            return rows if isinstance(rows, list) else []
        raise ValueError("type must be cron or kanban")
