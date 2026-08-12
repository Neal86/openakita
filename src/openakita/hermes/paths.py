"""Persistent data paths shared by Hermes stores and isolation state."""
from __future__ import annotations

import os
from pathlib import Path


def hermes_data_root() -> Path:
    """Return the durable OpenAkita data root used by Hermes state."""
    explicit = os.environ.get("OPENAKITA_DATA_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    try:
        from openakita.config import settings

        return (Path(settings.project_root) / "data").resolve()
    except Exception:
        return (Path.cwd() / "data").resolve()


def hermes_data_path(name: str) -> Path:
    return hermes_data_root() / name
