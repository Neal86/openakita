"""Agent execution-mode and Hermes instance persistence."""
from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from collections.abc import Callable
from collections.abc import Callable
from collections.abc import Callable
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from openakita.utils.atomic_io import atomic_json_write


def _now() -> str:
    return datetime.now(UTC).isoformat()


def safe_id(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    if not value:
        raise ValueError("profile id is required")
    return value[:64]


class ExecutionMode(StrEnum):
    NATIVE = "native"
    HERMES = "hermes"


class HermesInstanceMode(StrEnum):
    SHARED = "shared"
    DEDICATED = "dedicated"


class SubAgentMemoryMode(StrEnum):
    EPHEMERAL = "ephemeral"
    ISOLATED = "isolated"
    INHERIT_READONLY = "inherit_readonly"


class InstanceLifecycle(StrEnum):
    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class AgentExecutionConfig:
    profile_id: str
    execution_mode: ExecutionMode = ExecutionMode.NATIVE
    hermes_instance_mode: HermesInstanceMode = HermesInstanceMode.SHARED
    hermes_instance_id: str | None = None
    hermes_allow_sub_agents: bool = False
    hermes_sub_agent_memory_mode: SubAgentMemoryMode = SubAgentMemoryMode.EPHEMERAL
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.profile_id = safe_id(self.profile_id)
        if not isinstance(self.execution_mode, ExecutionMode):
            self.execution_mode = ExecutionMode(str(self.execution_mode))
        if not isinstance(self.hermes_instance_mode, HermesInstanceMode):
            self.hermes_instance_mode = HermesInstanceMode(str(self.hermes_instance_mode))
        if not isinstance(self.hermes_sub_agent_memory_mode, SubAgentMemoryMode):
            self.hermes_sub_agent_memory_mode = SubAgentMemoryMode(str(self.hermes_sub_agent_memory_mode))
        self.updated_at = _now()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["execution_mode"] = self.execution_mode.value
        data["hermes_instance_mode"] = self.hermes_instance_mode.value
        data["hermes_sub_agent_memory_mode"] = self.hermes_sub_agent_memory_mode.value
        return data


@dataclass
class HermesInstance:
    id: str
    name: str
    mode: HermesInstanceMode
    agent_profile_id: str | None = None
    container_name: str = ""
    image: str = "nousresearch/hermes-agent:latest"
    network: str = "openakita-agents"
    volume_name: str = ""
    base_url: str = ""
    enabled: bool = True
    lifecycle_status: InstanceLifecycle = InstanceLifecycle.PENDING
    health_status: str = "unknown"
    max_concurrency: int = 4
    current_inflight: int = 0
    consecutive_failures: int = 0
    last_success_at: str | None = None
    last_error: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.id = safe_id(self.id)
        if not isinstance(self.mode, HermesInstanceMode):
            self.mode = HermesInstanceMode(str(self.mode))
        if not isinstance(self.lifecycle_status, InstanceLifecycle):
            self.lifecycle_status = InstanceLifecycle(str(self.lifecycle_status))
        self.container_name = self.container_name or f"openakita-hermes-{self.id}"
        self.volume_name = self.volume_name or f"openakita_hermes_{self.id}_data"
        self.base_url = self.base_url or f"http://{self.container_name}:8642"
        self.max_concurrency = max(1, int(self.max_concurrency))
        self.current_inflight = max(0, int(self.current_inflight))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mode"] = self.mode.value
        data["lifecycle_status"] = self.lifecycle_status.value
        return data


class _JsonStore:
    def __init__(self, path: Path, key: str, factory: Callable[..., Any], identity: Callable[[Any], str]):
        self.path, self.key, self.factory, self.identity = Path(path), key, factory, identity
        self._lock = threading.RLock()

    def list(self):
        with self._lock:
            if not self.path.exists():
                return []
            try:
                raw = json.loads(self.path.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                return []
            return [self.factory(**row) for row in raw.get(self.key, []) if isinstance(row, dict)]

    def save(self, rows) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_json_write(self.path, {"version": 1, self.key: [row.to_dict() for row in rows]})

    def upsert(self, row):
        with self._lock:
            rows = self.list()
            wanted = self.identity(row)
            for index, current in enumerate(rows):
                if self.identity(current) == wanted:
                    rows[index] = row
                    break
            else:
                rows.append(row)
            self.save(rows)
            return row

    def delete(self, row_id: str) -> bool:
        with self._lock:
            rows = self.list()
            kept = [row for row in rows if self.identity(row) != row_id]
            if len(rows) == len(kept):
                return False
            self.save(kept)
            return True


def _data_path(name: str) -> Path:
    try:
        from openakita.config import settings
        return Path(settings.project_root) / "data" / name
    except Exception:
        return Path.cwd() / "data" / name


class AgentExecutionStore:
    def __init__(self, path: Path | None = None):
        self._store = _JsonStore(path or _data_path("agent_execution.json"), "agents", lambda **d: AgentExecutionConfig(**d), lambda x: x.profile_id)

    def list(self) -> list[AgentExecutionConfig]: return self._store.list()
    def get(self, profile_id: str) -> AgentExecutionConfig:
        profile_id = safe_id(profile_id)
        return next((x for x in self.list() if x.profile_id == profile_id), AgentExecutionConfig(profile_id))
    def upsert(self, config: AgentExecutionConfig) -> AgentExecutionConfig: return self._store.upsert(config)
    def delete(self, profile_id: str) -> bool: return self._store.delete(safe_id(profile_id))


class HermesInstanceStore:
    def __init__(self, path: Path | None = None):
        self._store = _JsonStore(path or _data_path("hermes_instances.json"), "instances", lambda **d: HermesInstance(**d), lambda x: x.id)

    def list(self) -> list[HermesInstance]: return self._store.list()
    def get(self, instance_id: str) -> HermesInstance | None: return next((x for x in self.list() if x.id == instance_id), None)
    def upsert(self, instance: HermesInstance) -> HermesInstance: return self._store.upsert(instance)
    def delete(self, instance_id: str) -> bool: return self._store.delete(safe_id(instance_id))
