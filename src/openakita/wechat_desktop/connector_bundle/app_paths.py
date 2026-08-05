from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "OpenAkita-WeChat-Connector"


def app_data_dir() -> Path:
    """Return a writable per-user directory for config and logs."""
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    base = Path(root) if root else Path.home() / ".openakita"
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


DATA_DIR = app_data_dir()
CONFIG_PATH = DATA_DIR / "config.yaml"
LOG_PATH = DATA_DIR / "connector.log"
