"""Persistent data paths shared by Hermes stores and isolation state."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from filelock import FileLock


def _project_data_root() -> Path:
    try:
        from openakita.config import settings

        return (Path(settings.project_root) / "data").resolve()
    except Exception:
        return (Path.cwd() / "data").resolve()


def hermes_data_root() -> Path:
    """Return the durable OpenAkita data root used by Hermes state."""
    explicit = os.environ.get("OPENAKITA_DATA_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return _project_data_root()


def _migrate_legacy(name: str, target: Path) -> None:
    """Copy legacy Hermes state once when OPENAKITA_DATA_DIR moves it."""
    if target.exists():
        return
    legacy = _project_data_root() / name
    try:
        if legacy.resolve() == target.resolve() or not legacy.exists():
            return
    except OSError:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(target.parent / ".hermes-data-migration.lock"))
    with lock:
        if target.exists() or not legacy.exists():
            return
        try:
            if legacy.is_dir():
                shutil.copytree(legacy, target)
            else:
                shutil.copy2(legacy, target)
        except OSError:
            # Migration is best-effort and never removes the legacy source.
            return


def hermes_data_path(name: str) -> Path:
    target = hermes_data_root() / name
    if os.environ.get("OPENAKITA_DATA_DIR", "").strip():
        _migrate_legacy(name, target)
    return target
