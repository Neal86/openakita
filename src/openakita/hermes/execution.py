"""Agent execution-mode and Hermes instance persistence."""
from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from filelock import FileLock

from openakita.utils.atomic_io import atomic_json_write

from .paths import hermes_data_path


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
    def __init__(
        self,
        path: Path,
        key: str,
        factory: Callable[..., Any],
        identity: Callable[[Any], str],
    ) -> None:
        self.path = Path(path)
        self.key = key
        self.factory = factory
        self.identity = identity
        self._lock = threading.RLock()
        self._file_lock = FileLock(str(self.path) + ".lock")

    def _read_unlocked(self) -> list[Any]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(raw, dict):
            return []
        raw_rows = raw.get(self.key, [])
        if not isinstance(raw_rows, list):
            return []
        rows: list[Any] = []
        for item in raw_rows:
            if not isinstance(item, dict):
                continue
            try:
                rows.append(self.factory(**item))
            except (TypeError, ValueError):
                continue
        return rows

    def _write_unlocked(self, rows: list[Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(
            self.path,
            {"version": 1, self.key: [row.to_dict() for row in rows]},
        )

    def list(self) -> list[Any]:
        with self._lock, self._file_lock:
            return self._read_unlocked()

    def save(self, rows: list[Any]) -> None:
        with self._lock, self._file_lock:
            self._write_unlocked(rows)

    def upsert(self, row: Any) -> Any:
        with self._lock, self._file_lock:
            rows = self._read_unlocked()
            wanted = self.identity(row)
            for index, current in enumerate(rows):
                if self.identity(current) == wanted:
                    rows[index] = row
                    break
            else:
                rows.append(row)
            self._write_unlocked(rows)
            return row

    def delete(self, row_id: str) -> bool:
        with self._lock, self._file_lock:
            rows = self._read_unlocked()
            kept = [row for row in rows if self.identity(row) != row_id]
            if len(rows) == len(kept):
                return False
            self._write_unlocked(kept)
            return True


class AgentExecutionStore:
    def __init__(self, path: Path | None = None) -> None:
        self._store = _JsonStore(
            path or hermes_data_path("agent_execution.json"),
            "agents",
            lambda **data: AgentExecutionConfig(**data),
            lambda item: item.profile_id,
        )

    def list(self) -> list[AgentExecutionConfig]:
        return self._store.list()

    def get(self, profile_id: str) -> AgentExecutionConfig:
        profile_id = safe_id(profile_id)
        return next(
            (item for item in self.list() if item.profile_id == profile_id),
            AgentExecutionConfig(profile_id),
        )

    def upsert(self, config: AgentExecutionConfig) -> AgentExecutionConfig:
        return self._store.upsert(config)

    def delete(self, profile_id: str) -> bool:
        return self._store.delete(safe_id(profile_id))


class HermesInstanceStore:
    def __init__(self, path: Path | None = None) -> None:
        self._store = _JsonStore(
            path or hermes_data_path("hermes_instances.json"),
            "instances",
            lambda **data: HermesInstance(**data),
            lambda item: item.id,
        )

    def list(self) -> list[HermesInstance]:
        return self._store.list()

    def get(self, instance_id: str) -> HermesInstance | None:
        instance_id = safe_id(instance_id)
        return next((item for item in self.list() if item.id == instance_id), None)

    def upsert(self, instance: HermesInstance) -> HermesInstance:
        return self._store.upsert(instance)

    def delete(self, instance_id: str) -> bool:
        return self._store.delete(safe_id(instance_id))
