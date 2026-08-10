from __future__ import annotations

import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
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


_CACHE_TTL_SECONDS = 45.0
_cache_lock = threading.RLock()
_cache_value: HermesCapabilities | None = None
_cache_at = 0.0
_cache_binary = ""


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


def _detect_uncached(hermes: str | None = None) -> HermesCapabilities:
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


def detect_capabilities(
    hermes: str | None = None,
    *,
    force: bool = False,
    ttl_seconds: float = _CACHE_TTL_SECONDS,
) -> HermesCapabilities:
    """Return Hermes capability flags with a short process-local cache.

    Dashboard requests used to spawn six ``hermes <command> --help`` subprocesses
    per API call. Capabilities change only when Hermes itself changes, so a
    short-lived cache preserves correctness while making the dashboard cheap.
    ``force=True`` is used by the explicit refresh/doctor surfaces.
    """
    global _cache_at, _cache_binary, _cache_value
    binary = hermes or shutil.which("hermes") or "hermes"
    now = time.monotonic()
    with _cache_lock:
        if (
            not force
            and _cache_value is not None
            and _cache_binary == binary
            and now - _cache_at < max(0.0, float(ttl_seconds))
        ):
            return _cache_value
        value = _detect_uncached(binary)
        _cache_value = value
        _cache_at = now
        _cache_binary = binary
        return value


def clear_capability_cache() -> None:
    global _cache_at, _cache_binary, _cache_value
    with _cache_lock:
        _cache_value = None
        _cache_at = 0.0
        _cache_binary = ""


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
