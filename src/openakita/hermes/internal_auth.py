"""Internal authentication shared by OpenAkita and embedded/dynamic Hermes runtimes."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from filelock import FileLock


def _default_secret_path() -> Path:
    explicit = os.environ.get("OPENAKITA_HERMES_AUTH_FILE", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    data_dir = os.environ.get("OPENAKITA_DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir).expanduser().resolve() / "hermes" / "internal_gateway_token"
    return Path.home() / ".openakita" / "data" / "hermes" / "internal_gateway_token"


def internal_gateway_secret() -> str:
    """Return the per-install secret used only for Hermes -> OpenAkita /v1 calls.

    An explicitly configured environment value wins. Otherwise a cryptographically
    random token is generated once and persisted outside source control. This keeps
    desktop/local installs zero-configuration while avoiding a published default key.
    Creation is serialized across backend processes so concurrent first startup cannot
    observe a just-created-but-not-yet-written empty secret file.
    """
    configured = os.environ.get("OPENAKITA_HERMES_LLM_API_KEY", "").strip()
    if configured:
        return configured

    path = _default_secret_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path) + ".lock")
    with lock:
        try:
            current = path.read_text("utf-8").strip()
            if current:
                return current
        except OSError:
            pass

        token = secrets.token_urlsafe(48)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(token + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return token
