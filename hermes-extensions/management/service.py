from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - surfaced as a clear runtime error when needed
    yaml = None

_PROFILE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _run(command: list[str], *, env: dict[str, str] | None = None, timeout: int = 60) -> str:
    proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=env, check=False)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "Hermes command failed").strip())
    return proc.stdout.strip()


def _safe_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if yaml is None:
        raise RuntimeError("PyYAML is required for Hermes management. Install hermes-extensions/requirements.txt")
    try:
        value = yaml.safe_load(path.read_text("utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _nested(data: dict[str, Any], *keys: str) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


class ManagementCenter:
    """Management layer over native Hermes Profiles and Projects.

    Reads are taken from Hermes-owned profile/project state. Mutations use the
    official Hermes CLI except SOUL.md edits, for which Hermes currently has no
    dedicated mutation command. SOUL writes are constrained to a validated
    profile home and use atomic replacement.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")).expanduser().resolve()
        self.hermes = shutil.which("hermes") or "hermes"

    # ------------------------------------------------------------------
    # Profile helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_profile(name: str | None) -> str:
        value = str(name or "default").strip().lower()
        if value == "default":
            return value
        if not _PROFILE_RE.fullmatch(value):
            raise ValueError("invalid profile name")
        return value

    def _profile_home(self, name: str | None) -> Path:
        profile = self._normalize_profile(name)
        if profile == "default":
            return self.root
        profiles_root = (self.root / "profiles").resolve()
        home = (profiles_root / profile).resolve()
        if profiles_root not in home.parents:
            raise ValueError("invalid profile path")
        if not home.is_dir():
            raise ValueError(f"unknown Hermes profile: {profile}")
        return home

    def _profile_cli(self, name: str | None) -> list[str]:
        profile = self._normalize_profile(name)
        return [self.hermes] if profile == "default" else [self.hermes, "-p", profile]

    def _env_for(self, name: str | None) -> dict[str, str]:
        env = os.environ.copy()
        env["HERMES_HOME"] = str(self._profile_home(name))
        return env

    def _active_profile(self) -> str:
        marker = self.root / "active_profile"
        try:
            value = marker.read_text("utf-8").strip().lower()
            if value and (value == "default" or _PROFILE_RE.fullmatch(value)):
                return value
        except OSError:
            pass
        return "default"

    def profile_names(self) -> list[str]:
        names = ["default"]
        root = self.root / "profiles"
        if root.is_dir():
            for item in sorted(root.iterdir(), key=lambda p: p.name.lower()):
                name = item.name.lower()
                if item.is_dir() and _PROFILE_RE.fullmatch(name):
                    names.append(name)
        return names

    def _parse_profile_show(self, text: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for raw in text.splitlines():
            if ":" not in raw:
                continue
            key, value = raw.split(":", 1)
            key = key.strip().lower().replace(" ", "_")
            value = value.strip()
            if key:
                result[key] = value
        model_text = str(result.get("model") or "")
        match = re.match(r"(.+?)\s*\(([^()]+)\)\s*$", model_text)
        if match:
            result["model"] = match.group(1).strip()
            result["provider"] = match.group(2).strip()
        return result

    def agent_get(self, name: str) -> dict[str, Any]:
        profile = self._normalize_profile(name)
        home = self._profile_home(profile)
        config = _safe_yaml(home / "config.yaml")
        metadata = _safe_yaml(home / "profile.yaml")
        show: dict[str, Any] = {}
        try:
            show = self._parse_profile_show(_run([self.hermes, "profile", "show", profile], timeout=30))
        except Exception as exc:
            show = {"status_error": str(exc)}

        soul_path = home / "SOUL.md"
        try:
            soul = soul_path.read_text("utf-8") if soul_path.exists() else ""
        except OSError:
            soul = ""

        skills_dir = home / "skills"
        skills_count = 0
        if skills_dir.is_dir():
            try:
                skills_count = sum(1 for p in skills_dir.iterdir() if p.is_dir())
            except OSError:
                pass

        model = _nested(config, "model", "default") or show.get("model") or ""
        provider = _nested(config, "model", "provider") or show.get("provider") or ""
        workspace = _nested(config, "terminal", "cwd") or ""
        gateway = show.get("gateway") or "unknown"
        description = str(metadata.get("description") or "")
        cron_path = home / "cron" / "jobs.json"
        cron_count = 0
        try:
            payload = json.loads(cron_path.read_text("utf-8")) if cron_path.exists() else {}
            jobs = payload.get("jobs", payload if isinstance(payload, list) else [])
            cron_count = len(jobs) if isinstance(jobs, list) else 0
        except Exception:
            pass

        return {
            "name": profile,
            "display_name": profile.replace("_", " ").replace("-", " ").title(),
            "description": description,
            "home": str(home),
            "model": str(model or ""),
            "provider": str(provider or ""),
            "workspace": str(workspace or ""),
            "gateway": str(gateway),
            "skills_count": skills_count,
            "cron_count": cron_count,
            "is_default": profile == self._active_profile(),
            "soul": soul,
            "config_exists": (home / "config.yaml").exists(),
            "env_exists": (home / ".env").exists(),
            "soul_exists": soul_path.exists(),
            "status_error": show.get("status_error"),
        }

    def agent_list(self) -> list[dict[str, Any]]:
        return [self.agent_get(name) for name in self.profile_names()]

    def agent_create(self, args: dict[str, Any]) -> dict[str, Any]:
        name = self._normalize_profile(str(args.get("name") or ""))
        if name == "default":
            raise ValueError("default profile already exists")
        command = [self.hermes, "profile", "create", name]
        mode = str(args.get("clone_mode") or "blank").strip().lower()
        source = str(args.get("clone_from") or "").strip().lower()
        if mode not in {"blank", "clone", "clone_all"}:
            raise ValueError("clone_mode must be blank, clone, or clone_all")
        if mode == "clone":
            command.append("--clone")
        elif mode == "clone_all":
            command.append("--clone-all")
        if source:
            self._profile_home(source)
            command += ["--clone-from", source]
            if mode == "blank":
                command.append("--clone")
        description = str(args.get("description") or "").strip()
        if description:
            command += ["--description", description]
        if bool(args.get("no_skills", False)):
            if mode != "blank" or source:
                raise ValueError("no_skills cannot be combined with cloning")
            command.append("--no-skills")
        output = _run(command, timeout=120)

        # Apply supported post-create config through the profile-scoped CLI.
        workspace = str(args.get("workspace") or "").strip()
        model = str(args.get("model") or "").strip()
        provider = str(args.get("provider") or "").strip()
        if workspace:
            self._set_config(name, "terminal.cwd", workspace)
        if provider:
            self._set_config(name, "model.provider", provider)
        if model:
            self._set_config(name, "model.default", model)
        soul = args.get("soul")
        if soul is not None:
            self._write_soul(name, str(soul))
        return {"ok": True, "output": output, "agent": self.agent_get(name)}

    def _set_config(self, profile: str, key: str, value: str) -> str:
        if not value:
            raise ValueError(f"{key} cannot be empty")
        return _run([*self._profile_cli(profile), "config", "set", key, value], env=self._env_for(profile))

    def _write_soul(self, profile: str, content: str) -> None:
        if len(content) > 200_000:
            raise ValueError("SOUL.md exceeds 200000 characters")
        home = self._profile_home(profile)
        target = home / "SOUL.md"
        fd, temp_path = tempfile.mkstemp(prefix="SOUL.", suffix=".tmp", dir=str(home))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            Path(temp_path).replace(target)
        finally:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass

    def agent_update(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        profile = self._normalize_profile(name)
        self._profile_home(profile)
        new_name = str(args.get("name") or "").strip().lower()
        if new_name and new_name != profile:
            new_name = self._normalize_profile(new_name)
            if profile == "default":
                raise ValueError("default profile cannot be renamed")
            _run([self.hermes, "profile", "rename", profile, new_name], timeout=60)
            profile = new_name

        if args.get("description") is not None:
            _run([self.hermes, "profile", "describe", profile, "--text", str(args.get("description") or "")])
        if args.get("workspace") is not None:
            self._set_config(profile, "terminal.cwd", str(args.get("workspace") or "."))
        if args.get("provider") is not None and str(args.get("provider") or "").strip():
            self._set_config(profile, "model.provider", str(args["provider"]).strip())
        if args.get("model") is not None and str(args.get("model") or "").strip():
            self._set_config(profile, "model.default", str(args["model"]).strip())
        if args.get("soul") is not None:
            self._write_soul(profile, str(args["soul"]))
        return {"ok": True, "agent": self.agent_get(profile)}

    def agent_action(self, name: str, action: str, value: str | None = None) -> dict[str, Any]:
        profile = self._normalize_profile(name)
        self._profile_home(profile)
        action = str(action or "").strip().lower()
        if action == "use":
            output = _run([self.hermes, "profile", "use", profile])
        elif action in {"gateway_start", "gateway_stop", "gateway_restart", "gateway_status"}:
            verb = action.split("_", 1)[1]
            output = _run([*self._profile_cli(profile), "gateway", verb], env=self._env_for(profile), timeout=90)
        elif action == "set_workspace":
            if not value:
                raise ValueError("set_workspace requires value")
            output = self._set_config(profile, "terminal.cwd", value)
        elif action == "export":
            target = value or str(self.root / "backups" / f"{profile}-profile.tar.gz")
            Path(target).expanduser().parent.mkdir(parents=True, exist_ok=True)
            output = _run([self.hermes, "profile", "export", profile, "-o", target], timeout=180)
            return {"ok": True, "action": action, "output": output, "path": target}
        else:
            raise ValueError("unsupported agent action")
        return {"ok": True, "action": action, "output": output, "agent": self.agent_get(profile)}

    def agent_delete(self, name: str) -> dict[str, Any]:
        profile = self._normalize_profile(name)
        if profile == "default":
            raise ValueError("default profile cannot be deleted")
        if profile == self._active_profile():
            raise ValueError("active/default-selected profile cannot be deleted; switch profiles first")
        self._profile_home(profile)
        output = _run([self.hermes, "profile", "delete", profile, "--yes"], timeout=120)
        return {"ok": True, "deleted": profile, "output": output}

    # ------------------------------------------------------------------
    # Project helpers. Projects are profile-scoped in Hermes.
    # ------------------------------------------------------------------
    def _project_cli(self, profile: str | None, *args: str) -> list[str]:
        return [*self._profile_cli(profile), "project", *args]

    @staticmethod
    def _parse_project_list(text: str, profile: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        pattern = re.compile(r"^([* ])\s+([^\s]+)\s{2,}(.+?)(?:\s+\[(\d+) folder\(s\)\])?$")
        for line in text.splitlines():
            match = pattern.match(line.rstrip())
            if not match:
                continue
            marker, slug, label, folders = match.groups()
            archived = label.endswith(" (archived)")
            if archived:
                label = label[: -len(" (archived)")]
            rows.append({
                "profile": profile,
                "slug": slug,
                "name": label.strip(),
                "archived": archived,
                "active": marker == "*",
                "folder_count": int(folders or 0),
            })
        return rows

    @staticmethod
    def _parse_project_show(text: str, profile: str) -> dict[str, Any]:
        lines = text.splitlines()
        if not lines:
            return {"profile": profile}
        head = re.match(r"^(\S+)\s+\[([^\]]+)\](\s+\(archived\))?", lines[0].strip())
        result: dict[str, Any] = {"profile": profile, "folders": []}
        if head:
            result.update({"slug": head.group(1), "id": head.group(2), "archived": bool(head.group(3))})
        in_folders = False
        for raw in lines[1:]:
            stripped = raw.strip()
            if stripped == "folders:":
                in_folders = True
                continue
            if in_folders and stripped:
                primary = stripped.startswith("*")
                value = stripped.lstrip("* ").strip()
                label = ""
                match = re.match(r"^(.*?)(?:\s+\(([^()]*)\))?$", value)
                if match:
                    path, label = match.group(1).strip(), str(match.group(2) or "")
                else:
                    path = value
                result["folders"].append({"path": path, "label": label, "is_primary": primary})
                continue
            in_folders = False
            if ":" in stripped:
                key, value = stripped.split(":", 1)
                key = key.strip()
                value = value.strip()
                mapping = {"name": "name", "about": "description", "board": "board", "primary": "primary_path"}
                if key in mapping:
                    result[mapping[key]] = value
        return result

    def project_list(self, profile: str | None = None, include_archived: bool = True) -> list[dict[str, Any]]:
        profiles = [self._normalize_profile(profile)] if profile else self.profile_names()
        rows: list[dict[str, Any]] = []
        for p in profiles:
            args = ["list"] + (["--all"] if include_archived else [])
            try:
                text = _run(self._project_cli(p, *args), env=self._env_for(p), timeout=30)
            except Exception:
                continue
            for row in self._parse_project_list(text, p):
                try:
                    row.update(self.project_get(row["slug"], p))
                except Exception:
                    pass
                rows.append(row)
        return rows

    def project_get(self, project: str, profile: str | None = None) -> dict[str, Any]:
        p = self._normalize_profile(profile)
        ident = str(project or "").strip()
        if not ident or len(ident) > 128 or any(ch in ident for ch in "\r\n\0"):
            raise ValueError("invalid project reference")
        text = _run(self._project_cli(p, "show", ident), env=self._env_for(p), timeout=30)
        row = self._parse_project_show(text, p)
        # Computed Agent association: an Agent is associated when its configured
        # terminal.cwd equals one of the native project folders.
        folder_paths = {str(f.get("path") or "") for f in row.get("folders", [])}
        agents: list[str] = []
        for agent in self.agent_list():
            workspace = str(agent.get("workspace") or "")
            if workspace and workspace in folder_paths:
                agents.append(str(agent["name"]))
        row["agents"] = agents
        return row

    def project_create(self, args: dict[str, Any]) -> dict[str, Any]:
        profile = self._normalize_profile(str(args.get("profile") or "default"))
        self._profile_home(profile)
        name = str(args.get("name") or "").strip()
        if not name:
            raise ValueError("project name is required")
        command = self._project_cli(profile, "create", name)
        folders = args.get("folders") or []
        if isinstance(folders, str):
            folders = [folders]
        for folder in folders:
            value = str(folder or "").strip()
            if value:
                command.append(value)
        for key, flag in (("slug", "--slug"), ("primary", "--primary"), ("description", "--description"), ("icon", "--icon"), ("color", "--color"), ("board", "--board")):
            value = str(args.get(key) or "").strip()
            if value:
                command += [flag, value]
        if bool(args.get("use", False)):
            command.append("--use")
        output = _run(command, env=self._env_for(profile), timeout=60)
        slug = str(args.get("slug") or "").strip()
        if not slug:
            match = re.search(r"Created project\s+(\S+)\s+\(", output)
            slug = match.group(1) if match else name
        project = self.project_get(slug, profile)

        agent = str(args.get("agent") or "").strip()
        if agent:
            primary = str(project.get("primary_path") or "")
            if not primary:
                raise ValueError("cannot assign agent: project has no primary folder")
            self._set_config(agent, "terminal.cwd", primary)
            project = self.project_get(slug, profile)
        return {"ok": True, "output": output, "project": project}

    def project_update(self, project: str, profile: str | None, args: dict[str, Any]) -> dict[str, Any]:
        p = self._normalize_profile(profile)
        current = self.project_get(project, p)
        ident = str(current.get("slug") or project)
        outputs: list[str] = []
        if args.get("name") is not None and str(args.get("name") or "").strip():
            outputs.append(_run(self._project_cli(p, "rename", ident, str(args["name"]).strip()), env=self._env_for(p)))
        if args.get("primary") is not None and str(args.get("primary") or "").strip():
            outputs.append(_run(self._project_cli(p, "set-primary", ident, str(args["primary"]).strip()), env=self._env_for(p)))
        if args.get("board") is not None:
            command = self._project_cli(p, "bind-board", ident)
            board = str(args.get("board") or "").strip()
            if board:
                command.append(board)
            outputs.append(_run(command, env=self._env_for(p)))
        add_folders = args.get("add_folders") or []
        if isinstance(add_folders, str):
            add_folders = [add_folders]
        for folder in add_folders:
            value = str(folder or "").strip()
            if value:
                outputs.append(_run(self._project_cli(p, "add-folder", ident, value), env=self._env_for(p)))
        remove_folders = args.get("remove_folders") or []
        if isinstance(remove_folders, str):
            remove_folders = [remove_folders]
        for folder in remove_folders:
            value = str(folder or "").strip()
            if value:
                outputs.append(_run(self._project_cli(p, "remove-folder", ident, value), env=self._env_for(p)))
        agent = str(args.get("agent") or "").strip()
        if agent:
            refreshed = self.project_get(ident, p)
            primary = str(refreshed.get("primary_path") or "")
            if not primary:
                raise ValueError("cannot assign agent: project has no primary folder")
            outputs.append(self._set_config(agent, "terminal.cwd", primary))
        return {"ok": True, "output": "\n".join(x for x in outputs if x), "project": self.project_get(ident, p)}

    def project_action(self, project: str, profile: str | None, action: str, value: str | None = None) -> dict[str, Any]:
        p = self._normalize_profile(profile)
        current = self.project_get(project, p)
        ident = str(current.get("slug") or project)
        action = str(action or "").strip().lower()
        if action in {"use", "archive", "restore"}:
            output = _run(self._project_cli(p, action, ident), env=self._env_for(p))
        elif action == "add_folder":
            if not value:
                raise ValueError("add_folder requires value")
            output = _run(self._project_cli(p, "add-folder", ident, value), env=self._env_for(p))
        elif action == "remove_folder":
            if not value:
                raise ValueError("remove_folder requires value")
            output = _run(self._project_cli(p, "remove-folder", ident, value), env=self._env_for(p))
        elif action == "set_primary":
            if not value:
                raise ValueError("set_primary requires value")
            output = _run(self._project_cli(p, "set-primary", ident, value), env=self._env_for(p))
        elif action == "bind_board":
            command = self._project_cli(p, "bind-board", ident)
            if value:
                command.append(value)
            output = _run(command, env=self._env_for(p))
        elif action == "assign_agent":
            if not value:
                raise ValueError("assign_agent requires an agent name")
            primary = str(current.get("primary_path") or "")
            if not primary:
                raise ValueError("project has no primary folder")
            output = self._set_config(value, "terminal.cwd", primary)
        else:
            raise ValueError("unsupported project action")
        return {"ok": True, "action": action, "output": output, "project": self.project_get(ident, p)}

    def overview(self) -> dict[str, Any]:
        agents = self.agent_list()
        projects = self.project_list(include_archived=True)
        active_projects = [p for p in projects if not p.get("archived")]
        running = [a for a in agents if str(a.get("gateway") or "").lower().startswith("running")]
        return {
            "counts": {
                "agents": len(agents),
                "running_agents": len(running),
                "projects": len(active_projects),
                "archived_projects": sum(1 for p in projects if p.get("archived")),
            },
            "agents": agents,
            "projects": projects,
            "active_profile": self._active_profile(),
        }
