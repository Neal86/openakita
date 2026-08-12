"""Persistent data paths shared by Hermes stores and isolation state."""
from __future__ import annotations

import os
import shutil
import time
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


def _copy_file_atomic(source: Path, target: Path) -> None:
    """Copy one migration file without exposing a partially written target."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.{time.time_ns()}.migration.tmp")
    try:
        shutil.copy2(source, tmp)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def _migrate_legacy(name: str, target: Path) -> None:
    """Copy legacy Hermes state once when OPENAKITA_DATA_DIR moves it.

    File-backed Hermes stores use ``.bak`` recovery. Migrate the backup beside
    the primary so a corrupt legacy primary remains recoverable after moving to
    a durable data root. If only the backup survived, seed the new primary from
    that backup as well. The legacy source is never removed.
    """
    if target.exists():
        return
    legacy = _project_data_root() / name
    legacy_backup = legacy.with_suffix(legacy.suffix + ".bak")
    try:
        if legacy.resolve() == target.resolve():
            return
        if not legacy.exists() and not legacy_backup.exists():
            return
    except OSError:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(target.parent / ".hermes-data-migration.lock"))
    with lock:
        if target.exists():
            return
        try:
            if legacy.is_dir():
                shutil.copytree(legacy, target)
                return
            target_backup = target.with_suffix(target.suffix + ".bak")
            if legacy.exists():
                _copy_file_atomic(legacy, target)
                if legacy_backup.exists():
                    _copy_file_atomic(legacy_backup, target_backup)
            elif legacy_backup.exists():
                _copy_file_atomic(legacy_backup, target)
                _copy_file_atomic(legacy_backup, target_backup)
        except OSError:
            # Migration is best-effort and never removes the legacy source.
            return


def hermes_data_path(name: str) -> Path:
    target = hermes_data_root() / name
    if os.environ.get("OPENAKITA_DATA_DIR", "").strip():
        _migrate_legacy(name, target)
    return target
