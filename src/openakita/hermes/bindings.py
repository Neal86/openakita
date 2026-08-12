"""Per-Agent Hermes runtime bindings kept separate from AgentProfile JSON."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from filelock import FileLock

from openakita.utils.atomic_io import atomic_json_write, read_json_safe

from .models import HermesRoutingPolicy, HermesRuntimeProvider
from .paths import hermes_data_path


@dataclass
class AgentHermesBinding:
    profile_id: str
    runtime_provider: HermesRuntimeProvider = HermesRuntimeProvider.LOCAL
    hermes_node_ids: list[str] = field(default_factory=list)
    hermes_routing_policy: HermesRoutingPolicy = HermesRoutingPolicy.PRIORITY
    hermes_fallback_enabled: bool = True
    required_capabilities: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.runtime_provider, HermesRuntimeProvider):
            self.runtime_provider = HermesRuntimeProvider(str(self.runtime_provider))
        if not isinstance(self.hermes_routing_policy, HermesRoutingPolicy):
            self.hermes_routing_policy = HermesRoutingPolicy(str(self.hermes_routing_policy))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["runtime_provider"] = self.runtime_provider.value
        data["hermes_routing_policy"] = self.hermes_routing_policy.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentHermesBinding:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class AgentHermesBindingStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or hermes_data_path("agent_hermes_bindings.json"))
        self._lock = threading.RLock()
        self._file_lock = FileLock(str(self.path) + ".lock")

    def _read_unlocked(self) -> list[AgentHermesBinding]:
        raw = read_json_safe(self.path)
        if not isinstance(raw, dict):
            return []
        raw_rows = raw.get("bindings", [])
        if not isinstance(raw_rows, list):
            return []
        rows: list[AgentHermesBinding] = []
        for item in raw_rows:
            if not isinstance(item, dict):
                continue
            try:
                rows.append(AgentHermesBinding.from_dict(item))
            except (TypeError, ValueError, AttributeError, OverflowError):
                # Keep valid bindings available when a single persisted row
                # was written by an older version or manually corrupted.
                continue
        return rows

    def list(self) -> list[AgentHermesBinding]:
        with self._lock, self._file_lock:
            return self._read_unlocked()

    def get(self, profile_id: str) -> AgentHermesBinding:
        return next(
            (item for item in self.list() if item.profile_id == profile_id),
            AgentHermesBinding(profile_id=profile_id),
        )

    def _save_unlocked(self, rows: list[AgentHermesBinding]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(
            self.path,
            {"version": 1, "bindings": [item.to_dict() for item in rows]},
        )

    def upsert(self, binding: AgentHermesBinding) -> AgentHermesBinding:
        with self._lock, self._file_lock:
            rows = self._read_unlocked()
            for index, current in enumerate(rows):
                if current.profile_id == binding.profile_id:
                    rows[index] = binding
                    break
            else:
                rows.append(binding)
            self._save_unlocked(rows)
            return binding

    def delete(self, profile_id: str) -> bool:
        with self._lock, self._file_lock:
            rows = self._read_unlocked()
            kept = [item for item in rows if item.profile_id != profile_id]
            if len(kept) == len(rows):
                return False
            self._save_unlocked(kept)
            return True
