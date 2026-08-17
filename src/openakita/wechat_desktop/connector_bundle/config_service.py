from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

APP_DIR = Path(os.environ.get("APPDATA", Path.home() / ".openakita")) / "OpenAkita" / "WeChatConnector"
CONFIG_PATH = APP_DIR / "config.yaml"
LOG_PATH = APP_DIR / "connector.log"


def ensure_app_dir() -> Path:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    return APP_DIR


def load_config() -> dict[str, Any]:
    ensure_app_dir()
    if not CONFIG_PATH.exists():
        return {}
    return yaml.safe_load(CONFIG_PATH.read_text("utf-8")) or {}


def save_config(data: dict[str, Any]) -> None:
    ensure_app_dir()
    CONFIG_PATH.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), "utf-8")
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


def clear_config() -> None:
    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()


def masked_token(token: str) -> str:
    token = token.strip()
    if len(token) <= 8:
        return "•" * len(token)
    return f"{token[:4]}…{token[-4:]}"
