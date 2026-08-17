"""Filesystem isolation helpers for profiles sharing one Hermes instance."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from openakita.utils.atomic_io import atomic_json_write

from .execution import safe_id
from .paths import hermes_data_path


class HermesIsolationManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or hermes_data_path("hermes_agents")).resolve()

    def profile_root(self, profile_id: str) -> Path:
        profile_id = safe_id(profile_id)
        path = (self.root / profile_id).resolve()
        if self.root not in path.parents:
            raise ValueError("invalid profile path")
        return path

    def ensure(
        self,
        profile_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        base = self.profile_root(profile_id)
        paths = {
            "root": base,
            "memory": base / "memory",
            "sessions": base / "sessions",
            "workspace": base / "workspace",
            "identity": base / "identity",
            "skills": base / "skills",
            "config": base / "config",
            "sub_agents": base / "sub_agents",
        }
        for path in paths.values():
            path.mkdir(parents=True, exist_ok=True)
        if metadata is not None:
            target = paths["config"] / "profile.json"
            atomic_json_write(target, metadata, fsync=True)
        return {key: str(value) for key, value in paths.items()}

    def sub_agent_root(
        self,
        parent_id: str,
        child_id: str,
        *,
        ephemeral: bool,
    ) -> Path:
        parent = self.profile_root(parent_id)
        child = safe_id(child_id)
        bucket = "ephemeral" if ephemeral else "persistent"
        path = (parent / "sub_agents" / bucket / child).resolve()
        if parent not in path.parents:
            raise ValueError("invalid child path")
        path.mkdir(parents=True, exist_ok=True)
        return path
