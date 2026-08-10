from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class HermesCapabilities:
    hermes: bool
    plugins: bool
    dashboard: bool
    profile: bool
    project: bool
    cron: bool
    kanban: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _supports(hermes: str, command: str) -> bool:
    try:
        proc = subprocess.run(
            [hermes, command, "--help"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception:
        return False
    text = f"{proc.stdout}\n{proc.stderr}".lower()
    if "invalid choice" in text or "no such command" in text or "unknown command" in text:
        return False
    return proc.returncode == 0


def detect_capabilities(hermes: str | None = None) -> HermesCapabilities:
    binary = hermes or shutil.which("hermes") or "hermes"
    available = shutil.which(binary) is not None if binary == "hermes" else True
    if not available:
        return HermesCapabilities(False, False, False, False, False, False, False)
    return HermesCapabilities(
        hermes=True,
        plugins=_supports(binary, "plugins"),
        dashboard=_supports(binary, "dashboard"),
        profile=_supports(binary, "profile"),
        project=_supports(binary, "project"),
        cron=_supports(binary, "cron"),
        kanban=_supports(binary, "kanban"),
    )


def project_unavailable_payload() -> dict[str, Any]:
    return {
        "supported": False,
        "items": [],
        "message": (
            "This Hermes installation does not expose the native 'hermes project' command. "
            "Agents, Tasks, Dashboard and WeChat remain available. Projects will enable automatically "
            "after Hermes is upgraded to a build that provides native Projects."
        ),
    }
