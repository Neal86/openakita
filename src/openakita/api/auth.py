"""
Web access authentication for OpenAkita.

Single-password mode with JWT tokens. Local requests (127.0.0.1) are exempt
from authentication to preserve the desktop experience.

Storage: data/web_access.json
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from filelock import FileLock

from openakita.utils.atomic_io import atomic_json_write, read_json_safe

from ..core.auth.tokens import TokenClaims, decode_jwt, encode_jwt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCESS_TOKEN_TTL = 24 * 3600  # 24 hours
REFRESH_TOKEN_TTL = 90 * 24 * 3600  # 90 days
REFRESH_COOKIE_NAME = "openakita_refresh"
PASSWORD_ENV_VAR = "OPENAKITA_WEB_PASSWORD"

AUTH_EXEMPT_PATHS = frozenset(
    {
        "/",
        "/api/health",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/refresh",
        "/api/auth/check",
        "/api/auth/setup",
        "/api/auth/setup-status",
        "/api/logs/frontend",
        "/openapi.json",
        # Connector pairing is authenticated by a one-time pairing code.
        # Keep only the redemption endpoint public; node management and
        # pairing-code creation still require normal web authentication.
        "/api/wechat-desktop/pair",
        "/api/windows-connector/pair",
    }
)
AUTH_EXEMPT_PREFIXES = ("/web", "/ws", "/docs", "/redoc", "/user-docs")

# ---------------------------------------------------------------------------
# Password hashing (scrypt, stdlib)
# ---------------------------------------------------------------------------


def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """Hash password with scrypt. Returns (hash_hex, salt_hex)."""
    if salt is None:
        salt = secrets.token_bytes(16)
    h = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=16384,
        r=8,
        p=1,
        dklen=32,
    )
    return h.hex(), salt.hex()


def _verify_password(password: str, hash_hex: str, salt_hex: str) -> bool:
    try:
        h = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=16384,
            r=8,
            p=1,
            dklen=32,
        )
        return hmac.compare_digest(h.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Web Access config (durable data root)
# ---------------------------------------------------------------------------


def resolve_web_access_data_dir() -> Path:
    """Return the durable directory that owns ``web_access.json``.

    ``OPENAKITA_DATA_DIR`` is authoritative for container/VPS deployments.
    Otherwise reuse ``settings.data_dir`` when available, with the historical
    ``project_root/data`` directory as fallback. When a durable root is newly
    introduced, migrate only the authentication JSON and do so through the
    existing validated atomic-I/O path. Other server data keeps its historical
    location unless it has its own explicit persistence migration.
    """
    explicit = os.environ.get("OPENAKITA_DATA_DIR", "").strip()
    legacy = Path.cwd() / "data"
    if explicit:
        target = Path(explicit).expanduser().resolve()
        try:
            from openakita.config import settings

            legacy = (Path(settings.project_root) / "data").resolve()
        except Exception:
            legacy = legacy.resolve()
    else:
        try:
            from openakita.config import settings

            legacy = (Path(settings.project_root) / "data").resolve()
            configured = getattr(settings, "data_dir", None)
            target = Path(configured).expanduser() if configured else legacy
            if not target.is_absolute():
                target = Path(settings.project_root) / target
            target = target.resolve()
        except Exception:
            target = legacy.resolve()

    target.mkdir(parents=True, exist_ok=True)
    target_file = target / "web_access.json"
    legacy_file = legacy / "web_access.json"
    if target != legacy and not target_file.exists() and legacy_file.exists():
        migration_lock = FileLock(str(target_file) + ".migration.lock")
        with migration_lock:
            if not target_file.exists() and legacy_file.exists():
                legacy_data = read_json_safe(legacy_file)
                if isinstance(legacy_data, dict):
                    try:
                        atomic_json_write(
                            target_file,
                            legacy_data,
                            backup=True,
                            fsync=True,
                            allow_fallback=False,
                        )
                        logger.info(
                            "Migrated web access config from %s to durable root %s",
                            legacy_file,
                            target_file,
                        )
                    except OSError as exc:
                        logger.warning(
                            "Failed to migrate web access config from %s to %s: %s",
                            legacy_file,
                            target_file,
                            exc,
                        )
                else:
                    logger.error(
                        "Legacy web access config %s is not recoverable; "
                        "leaving durable target absent",
                        legacy_file,
                    )
    return target


class WebAccessConfig:
    """Manages the web_access.json file."""

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "web_access.json"
        self._data: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._file_lock = FileLock(str(self._path) + ".lock")
        self._disk_version: tuple[int, int] | None = None
        self._load()

    def _read_disk_locked(self) -> dict[str, Any]:
        raw = read_json_safe(self._path)
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            logger.error("Invalid web access config root in %s; ignoring it", self._path)
            return {}
        return dict(raw)

    def _stat_disk_version(self) -> tuple[int, int] | None:
        try:
            stat = self._path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def _save_locked(self) -> None:
        atomic_json_write(
            self._path,
            self._data,
            backup=True,
            fsync=True,
            allow_fallback=False,
        )
        self._disk_version = self._stat_disk_version()

    def _load(self) -> None:
        with self._lock, self._file_lock:
            self._data = self._read_disk_locked()
            env_password = os.environ.get(PASSWORD_ENV_VAR, "").strip()
            needs_save = False

            if not self._data.get("jwt_secret"):
                self._data["jwt_secret"] = secrets.token_hex(32)
                needs_save = True

            if not self._data.get("data_epoch"):
                self._data["data_epoch"] = secrets.token_hex(8)
                needs_save = True

            if not self._data.get("token_version"):
                self._data["token_version"] = 1
                needs_save = True

            if env_password:
                existing_hash = self._data.get("password_hash", "")
                existing_salt = self._data.get("password_salt", "")
                if (
                    not existing_hash
                    or not existing_salt
                    or not _verify_password(env_password, existing_hash, existing_salt)
                ):
                    hash_hex, salt_hex = _hash_password(env_password)
                    self._data["password_hash"] = hash_hex
                    self._data["password_salt"] = salt_hex
                    self._data["password_plain_hint"] = _make_hint(env_password)
                    self._data["password_user_set"] = True
                    needs_save = True
                elif not self._data.get("password_user_set"):
                    self._data["password_user_set"] = True
                    needs_save = True

            if needs_save:
                self._data["updated_at"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                )
                self._save_locked()
            else:
                self._disk_version = self._stat_disk_version()

    def _refresh_for_mutation_locked(self) -> None:
        latest = self._read_disk_locked()
        if latest:
            self._data = latest
        self._disk_version = self._stat_disk_version()

    def _refresh_if_changed(self) -> None:
        observed = self._stat_disk_version()
        if observed == self._disk_version:
            return
        with self._lock, self._file_lock:
            observed = self._stat_disk_version()
            if observed == self._disk_version:
                return
            latest = self._read_disk_locked()
            if latest:
                self._data = latest
            self._disk_version = self._stat_disk_version()

    @property
    def jwt_secret(self) -> str:
        self._refresh_if_changed()
        return self._data["jwt_secret"]

    @property
    def token_version(self) -> int:
        self._refresh_if_changed()
        return self._data.get("token_version", 1)

    @property
    def data_epoch(self) -> str:
        self._refresh_if_changed()
        return self._data.get("data_epoch", "")

    @property
    def password_hint(self) -> str:
        self._refresh_if_changed()
        return self._data.get("password_plain_hint", "")

    def verify_password(self, password: str) -> bool:
        self._refresh_if_changed()
        with self._lock:
            h = self._data.get("password_hash", "")
            s = self._data.get("password_salt", "")
        if not h or not s:
            return False
        return _verify_password(password, h, s)

    @property
    def password_user_set(self) -> bool:
        self._refresh_if_changed()
        return self._data.get("password_user_set", False)

    @property
    def has_password_set(self) -> bool:
        """Whether a usable password is currently stored.

        Used by :mod:`openakita.api.setup_state` to decide whether the Setup
        flow should be presented to non-loopback clients. Returns ``True`` iff
        both the hash and salt fields are present and non-empty — this is
        the same condition that :meth:`verify_password` checks before
        comparing.
        """
        self._refresh_if_changed()
        return bool(self._data.get("password_hash")) and bool(self._data.get("password_salt"))

    def change_password(self, new_password: str) -> None:
        hash_hex, salt_hex = _hash_password(new_password)
        with self._lock, self._file_lock:
            self._refresh_for_mutation_locked()
            self._data["password_hash"] = hash_hex
            self._data["password_salt"] = salt_hex
            self._data["password_plain_hint"] = _make_hint(new_password)
            self._data["password_user_set"] = True
            self._data["token_version"] = int(self._data.get("token_version", 1)) + 1
            self._data["updated_at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            )
            self._save_locked()

    def clear_password(self) -> None:
        """Drop the password hash so the Setup flow is required again.

        Used by the ``openakita reset-password`` CLI. Bumps ``token_version``
        so any access / refresh token previously issued under the old password
        is invalidated immediately (relevant when a running process keeps the
        config in memory after the file change — even though the password is
        gone, stale tokens shouldn't keep working).

        ``jwt_secret`` and ``data_epoch`` are intentionally preserved: rotating
        them would invalidate session storage signed under those keys, which
        is more disruptive than necessary for a password reset.
        """
        with self._lock, self._file_lock:
            self._refresh_for_mutation_locked()
            self._data.pop("password_hash", None)
            self._data.pop("password_salt", None)
            self._data.pop("password_plain_hint", None)
            self._data["password_user_set"] = False
            self._data["token_version"] = int(self._data.get("token_version", 1)) + 1
            self._data["updated_at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            )
            self._save_locked()

    def create_access_token(self) -> str:
        claims = TokenClaims(
            token_type="access",
            subject="desktop_user",
            expires_in=ACCESS_TOKEN_TTL,
            version=self.token_version,
            scope=["web:access"],
        )
        return encode_jwt(claims.to_payload(), self.jwt_secret)

    def create_refresh_token(self) -> str:
        claims = TokenClaims(
            token_type="refresh",
            subject="desktop_user",
            expires_in=REFRESH_TOKEN_TTL,
            version=self.token_version,
            scope=["web:refresh"],
        )
        return encode_jwt(claims.to_payload(), self.jwt_secret)

    def validate_access_token(self, token: str) -> bool:
        payload = decode_jwt(token, self.jwt_secret)
        if not payload:
            return False
        if payload.get("type") != "access":
            return False
        if payload.get("ver") != self.token_version:
            return False
        return True

    def validate_refresh_token(self, token: str) -> dict[str, Any] | None:
        payload = decode_jwt(token, self.jwt_secret)
        if not payload:
            return None
        if payload.get("type") != "refresh":
            return None
        if payload.get("ver") != self.token_version:
            return None
        return payload


def _make_hint(password: str) -> str:
    if len(password) <= 6:
        return password[0] + "..." + password[-1] if len(password) >= 2 else "***"
    return password[:3] + "..." + password[-3:]


# ---------------------------------------------------------------------------
# Rate limiter (simple in-memory, per-IP)
# ---------------------------------------------------------------------------


class RateLimiter:
    """Simple sliding-window rate limiter.

    Tracks the timestamps of *failures* (the caller decides what counts as
    a failure by being explicit about :meth:`register_failure` vs
    :meth:`clear`). :meth:`is_allowed` returns False when the most recent
    window already contains the cap, and :meth:`retry_after_seconds` tells
    the HTTP layer how long until the oldest hit ages out so a meaningful
    ``Retry-After`` header can be returned.
    """

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._hits: dict[str, list[float]] = {}

    def _trim(self, key: str, now: float) -> list[float]:
        timestamps = [t for t in self._hits.get(key, []) if now - t < self._window]
        if timestamps:
            self._hits[key] = timestamps
        else:
            self._hits.pop(key, None)
        return timestamps

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        return len(self._trim(key, now)) < self._max

    def register_failure(self, key: str) -> None:
        now = time.time()
        timestamps = self._trim(key, now)
        timestamps.append(now)
        self._hits[key] = timestamps

    def clear(self, key: str) -> None:
        self._hits.pop(key, None)

    def retry_after_seconds(self, key: str) -> int:
        now = time.time()
        timestamps = self._trim(key, now)
        if not timestamps:
            return 0
        oldest = timestamps[0]
        return max(1, int(self._window - (now - oldest)))


# Global rate limiters
# 5 failed logins / 5 minutes is the canonical "annoy a bot, don't annoy a
# user" setting. The previous 5/60s was too aggressive (a legitimate user
# trying three wrong passwords could lock themselves out for a minute);
# extending the window to 5 minutes while keeping the count gives the user
# the same number of tries but discourages credential-stuffing scripts.
_login_limiter = RateLimiter(max_requests=5, window_seconds=300)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


def get_client_ip(request: Request, *, trust_proxy: bool = False) -> str:
    """Return the client IP, respecting X-Forwarded-For when trust_proxy is on."""
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_local_request(request: Request) -> bool:
    """Check if request originates from localhost (direct connection only).

    Handles plain IPv4/IPv6 loopback as well as IPv4-mapped IPv6 addresses
    (``::ffff:127.0.0.1``) which some OS/Uvicorn combinations report when the
    server binds to ``0.0.0.0`` on dual-stack systems (common on Windows).
    """
    if not request.client:
        return False
    host = request.client.host
    if host in ("127.0.0.1", "::1", "localhost"):
        return True
    # IPv4-mapped IPv6: ::ffff:127.0.0.1
    if host.startswith("::ffff:") and host[7:] == "127.0.0.1":
        return True
    return False


def is_trusted_local(request: Request) -> bool:
    """Return True when the request is a direct local connection.

    A direct local connection is one that:

    - originates from a loopback address (see :func:`_is_local_request`), and
    - is *not* being forwarded by a reverse proxy.

    The second clause matters under ``TRUST_PROXY=true``: an Nginx/Caddy in
    front of the server will *itself* connect from 127.0.0.1 but always sets
    ``X-Forwarded-For``. A direct local connection (e.g. Tauri / curl on the
    same host) comes from 127.0.0.1 with *no* ``X-Forwarded-For`` header.
    We use that distinction to tell the two apart so that proxied requests
    are still subject to authentication / setup gating.

    Shared by :func:`create_auth_middleware` and
    :mod:`openakita.api.setup_state` — keep them aligned by going through
    this single helper.
    """
    if not _is_local_request(request):
        return False
    if request.headers.get("x-forwarded-for") or request.headers.get("forwarded"):
        return False
    return True


def is_private_direct_request(request: Request) -> bool:
    """Allow keyless /v1 only for direct private-network peers."""
    if not request.client:
        return False
    if request.headers.get("x-forwarded-for") or request.headers.get("forwarded"):
        return False
    try:
        address = ipaddress.ip_address(request.client.host.removeprefix("::ffff:"))
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


def _is_auth_exempt(path: str) -> bool:
    """Check auth exemptions using real path-segment boundaries.

    A raw ``startswith`` would make ``/webhook`` inherit the exemption for
    ``/web`` and ``/docs-private`` inherit ``/docs``. Only the exact path or a
    slash-delimited child path is exempt.
    """
    if path in AUTH_EXEMPT_PATHS:
        return True
    return any(
        path == prefix or path.startswith(prefix.rstrip("/") + "/")
        for prefix in AUTH_EXEMPT_PREFIXES
    )


def create_auth_middleware(config: WebAccessConfig):
    """Create the authentication middleware function."""

    async def auth_middleware(request: Request, call_next):
        # CORS preflight must always pass through (browser sends OPTIONS without auth)
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path

        # Hermes uses this OpenAI-compatible gateway only over the direct
        # Docker/private network. Requests carrying proxy forwarding headers
        # still go through normal web authentication.
        if path.startswith("/v1/") and is_private_direct_request(request):
            return await call_next(request)

        # Static files and auth endpoints are always accessible
        if _is_auth_exempt(path):
            return await call_next(request)

        # Direct local connections bypass auth (Tauri desktop, curl on the
        # same host). Reverse-proxy-forwarded requests still need a token even
        # when they originate from 127.0.0.1, because the proxy itself always
        # connects from loopback. See :func:`is_trusted_local`.
        if is_trusted_local(request):
            return await call_next(request)

        # Check Authorization header
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if config.validate_access_token(token):
                return await call_next(request)

        # Check query parameter token (for <img> / <audio> tags that can't set headers)
        query_token = request.query_params.get("token", "")
        if query_token and config.validate_access_token(query_token):
            return await call_next(request)

        # Check X-API-Key header (for programmatic access)
        api_key = request.headers.get("x-api-key", "")
        if api_key and config.verify_password(api_key):
            return await call_next(request)

        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )

    return auth_middleware
