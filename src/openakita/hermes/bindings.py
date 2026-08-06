"""Per-Agent Hermes runtime bindings kept separate from AgentProfile JSON.

This preserves backward compatibility while exposing the same fields planned for
AgentProfile. The API can later migrate them inline without changing routing.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from openakita.utils.atomic_io import atomic_json_write

from .models import HermesRoutingPolicy, HermesRuntimeProvider


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
    def from_dict(cls, data: dict[str, Any]) -> "AgentHermesBinding":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class AgentHermesBindingStore:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            try:
                from openakita.config import settings

                path = Path(settings.project_root) / "data" / "agent_hermes_bindings.json"
            except Exception:
                path = Path.cwd() / "data" / "agent_hermes_bindings.json"
        self.path = Path(path)
        self._lock = threading.RLock()

    def list(self) -> list[AgentHermesBinding]:
        with self._lock:
            if not self.path.exists():
                return []
            try:
                raw = json.loads(self.path.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                return []
            return [AgentHermesBinding.from_dict(x) for x in raw.get("bindings", [])]

    def get(self, profile_id: str) -> AgentHermesBinding:
        return next(
            (item for item in self.list() if item.profile_id == profile_id),
            AgentHermesBinding(profile_id=profile_id),
        )

    def upsert(self, binding: AgentHermesBinding) -> AgentHermesBinding:
        with self._lock:
            rows = self.list()
            for index, current in enumerate(rows):
                if current.profile_id == binding.profile_id:
                    rows[index] = binding
                    break
            else:
                rows.append(binding)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_json_write(self.path, {"version": 1, "bindings": [x.to_dict() for x in rows]})
            return binding
