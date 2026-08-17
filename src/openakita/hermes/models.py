"""Data models for remote Hermes Agent runtimes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class HermesRuntimeProvider(StrEnum):
    LOCAL = "local"
    HERMES = "hermes"
    AUTO = "auto"


class HermesRoutingPolicy(StrEnum):
    PRIORITY = "priority"
    WEIGHTED = "weighted"
    ROUND_ROBIN = "round_robin"
    LEAST_CONNECTIONS = "least_connections"
    PRIMARY_BACKUP = "primary_backup"


class HermesHealthStatus(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    DISABLED = "disabled"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class HermesNode:
    id: str
    name: str
    base_url: str
    api_key_env: str = ""
    enabled: bool = True
    priority: int = 100
    weight: int = 1
    capabilities: list[str] = field(default_factory=lambda: ["text", "tools"])
    tags: list[str] = field(default_factory=list)
    max_concurrency: int = 4
    current_inflight: int = 0
    health_status: HermesHealthStatus = HermesHealthStatus.UNKNOWN
    consecutive_failures: int = 0
    last_success_at: str | None = None
    last_error: str | None = None
    timeout_seconds: int = 180
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.id = self.id.strip()
        self.name = self.name.strip()
        self.base_url = self.base_url.rstrip("/")
        self.priority = max(0, int(self.priority))
        self.weight = max(1, int(self.weight))
        self.max_concurrency = max(1, int(self.max_concurrency))
        self.current_inflight = max(0, int(self.current_inflight))
        self.timeout_seconds = max(1, int(self.timeout_seconds))
        if not isinstance(self.health_status, HermesHealthStatus):
            try:
                self.health_status = HermesHealthStatus(str(self.health_status))
            except ValueError:
                self.health_status = HermesHealthStatus.UNKNOWN

    @property
    def available(self) -> bool:
        return (
            self.enabled
            and self.health_status not in {HermesHealthStatus.UNHEALTHY, HermesHealthStatus.DISABLED}
            and self.current_inflight < self.max_concurrency
        )

    def supports(self, required: set[str]) -> bool:
        return not required or required.issubset(set(self.capabilities))

    def mark_success(self) -> None:
        self.consecutive_failures = 0
        self.last_success_at = _now()
        self.last_error = None
        self.health_status = HermesHealthStatus.HEALTHY
        self.updated_at = _now()

    def mark_failure(self, error: str, threshold: int = 3) -> None:
        self.consecutive_failures += 1
        self.last_error = error[:1000]
        self.health_status = (
            HermesHealthStatus.UNHEALTHY
            if self.consecutive_failures >= threshold
            else HermesHealthStatus.DEGRADED
        )
        self.updated_at = _now()

    def to_dict(self, *, include_secret_reference: bool = True) -> dict[str, Any]:
        data = asdict(self)
        data["health_status"] = self.health_status.value
        if not include_secret_reference:
            data.pop("api_key_env", None)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HermesNode:
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in known})
