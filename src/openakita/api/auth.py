"""
Web access authentication for OpenAkita.

Single-password mode with JWT tokens. Local requests (127.0.0.1) are exempt
from authentication to preserve the desktop experience.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from ..core.auth.tokens import TokenClaims, decode_jwt, encode_jwt

logger = logging.getLogger(__name__)

ACCESS_TOKEN_TTL = 24 * 3600
REFRESH_TOKEN_TTL = 90 * 24 * 3600
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
        "/api/wechat-desktop/pair",
    }
)
AUTH_EXEMPT_PREFIXES = ("/web/", "/web", "/ws/", "/docs", "/openapi.json", "/redoc", "/user-docs")


def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return h.hex(), salt.hex()


def _verify_password(password: str, hash_hex: str, salt_hex: str) -> bool:
    try:
        h = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(h.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


class WebAccessConfig:
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "web_access.json"
        self._data: dict[str, Any] = {}
        self._lock = __import__("threading").Lock()
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text("utf-8"))
            except Exception:
                logger.error("Failed to read %s — regenerating fresh config", self._path, exc_info=True)
                self._data = {}
        env_password = os.environ.get(PASSWORD_ENV_VAR, "").strip()
        needs_save = False
        if not self._data.get("jwt_secret"):
            self._data["jwt_secret"] = secrets.token_hex(32); needs_save = True
        if not self._data.get("data_epoch"):
            self._data["data_epoch"] = secrets.token_hex(8); needs_save = True
        if not self._data.get("token_version"):
            self._data["token_version"] = 1; needs_save = True
        if env_password:
            existing_hash = self._data.get("password_hash", "")
            existing_salt = self._data.get("password_salt", "")
            if not existing_hash or not existing_salt or not _verify_password(env_password, existing_hash, existing_salt):
                hash_hex, salt_hex = _hash_password(env_password)
                self._data["password_hash"] = hash_hex
                self._data["password_salt"] = salt_hex
                self._data["password_plain_hint"] = _make_hint(env_password)
                self._data["password_user_set"] = True
                needs_save = True
            elif not self._data.get("password_user_set"):
                self._data["password_user_set"] = True; needs_save = True
        if needs_save:
            self._data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._save()

    def _save(self) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            payload = json.dumps(self._data, indent=2) + "\n"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload); f.flush(); os.fsync(f.fileno())
            os.replace(tmp, self._path)
            if os.name == "posix":
                try:
                    dir_fd = os.open(str(self._path.parent), os.O_RDONLY)
                    try: os.fsync(dir_fd)
                    finally: os.close(dir_fd)
                except OSError as exc:
                    logger.warning("Failed to fsync data dir %s: %s", self._path.parent, exc)

    @property
    def jwt_secret(self) -> str: return self._data["jwt_secret"]
    @property
    def token_version(self) -> int: return self._data.get("token_version", 1)
    @property
    def data_epoch(self) -> str: return self._data.get("data_epoch", "")
    @property
    def password_hint(self) -> str: return self._data.get("password_plain_hint", "")
    @property
    def password_user_set(self) -> bool: return self._data.get("password_user_set", False)
    @property
    def has_password_set(self) -> bool: return bool(self._data.get("password_hash")) and bool(self._data.get("password_salt"))

    def verify_password(self, password: str) -> bool:
        h, s = self._data.get("password_hash", ""), self._data.get("password_salt", "")
        return bool(h and s and _verify_password(password, h, s))

    def change_password(self, new_password: str) -> None:
        hash_hex, salt_hex = _hash_password(new_password)
        self._data.update(password_hash=hash_hex, password_salt=salt_hex, password_plain_hint=_make_hint(new_password), password_user_set=True)
        self._data["token_version"] = self.token_version + 1
        self._data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._save()

    def clear_password(self) -> None:
        for key in ("password_hash", "password_salt", "password_plain_hint"):
            self._data.pop(key, None)
        self._data["password_user_set"] = False
        self._data["token_version"] = self.token_version + 1
        self._data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._save()

    def create_access_token(self) -> str:
        claims = TokenClaims(token_type="access", subject="desktop_user", expires_in=ACCESS_TOKEN_TTL, version=self.token_version, scope=["web:access"])
        return encode_jwt(claims.to_payload(), self.jwt_secret)

    def create_refresh_token(self) -> str:
        claims = TokenClaims(token_type="refresh", subject="desktop_user", expires_in=REFRESH_TOKEN_TTL, version=self.token_version, scope=["web:refresh"])
        return encode_jwt(claims.to_payload(), self.jwt_secret)

    def validate_access_token(self, token: str) -> bool:
        payload = decode_jwt(token, self.jwt_secret)
        return bool(payload and payload.get("type") == "access" and payload.get("ver") == self.token_version)

    def validate_refresh_token(self, token: str) -> dict[str, Any] | None:
        payload = decode_jwt(token, self.jwt_secret)
        if not payload or payload.get("type") != "refresh" or payload.get("ver") != self.token_version:
            return None
        return payload


def _make_hint(password: str) -> str:
    if len(password) <= 6:
        return password[0] + "..." + password[-1] if len(password) >= 2 else "***"
    return password[:3] + "..." + password[-3:]


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self._max, self._window, self._hits = max_requests, window_seconds, {}
    def _trim(self, key: str, now: float) -> list[float]:
        timestamps = [t for t in self._hits.get(key, []) if now - t < self._window]
        if timestamps: self._hits[key] = timestamps
        else: self._hits.pop(key, None)
        return timestamps
    def is_allowed(self, key: str) -> bool: return len(self._trim(key, time.time())) < self._max
    def register_failure(self, key: str) -> None:
        now = time.time(); timestamps = self._trim(key, now); timestamps.append(now); self._hits[key] = timestamps
    def clear(self, key: str) -> None: self._hits.pop(key, None)
    def retry_after_seconds(self, key: str) -> int:
        now = time.time(); timestamps = self._trim(key, now)
        return 0 if not timestamps else max(1, int(self._window - (now - timestamps[0])))


_login_limiter = RateLimiter(max_requests=5, window_seconds=300)


def get_client_ip(request: Request, *, trust_proxy: bool = False) -> str:
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded: return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_local_request(request: Request) -> bool:
    if not request.client: return False
    host = request.client.host
    return host in ("127.0.0.1", "::1", "localhost") or (host.startswith("::ffff:") and host[7:] == "127.0.0.1")


def is_trusted_local(request: Request) -> bool:
    if not _is_local_request(request): return False
    trust_proxy = os.environ.get("TRUST_PROXY", "").lower() in ("1", "true", "yes")
    return not (trust_proxy and request.headers.get("x-forwarded-for"))


def is_private_direct_request(request: Request) -> bool:
    """Allow the keyless /v1 gateway only for direct RFC1918/link-local peers.

    Reverse-proxy traffic is rejected even when the proxy itself connects from
    a private Docker address, because forwarded headers prove the request did
    not originate from the Hermes container directly.
    """
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
    return path in AUTH_EXEMPT_PATHS or any(path.startswith(prefix) for prefix in AUTH_EXEMPT_PREFIXES)


def create_auth_middleware(config: WebAccessConfig):
    async def auth_middleware(request: Request, call_next):
        if request.method == "OPTIONS": return await call_next(request)
        path = request.url.path
        if path.startswith("/v1/") and is_private_direct_request(request):
            return await call_next(request)
        if _is_auth_exempt(path) or is_trusted_local(request):
            return await call_next(request)
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer ") and config.validate_access_token(auth_header[7:]):
            return await call_next(request)
        query_token = request.query_params.get("token", "")
        if query_token and config.validate_access_token(query_token):
            return await call_next(request)
        api_key = request.headers.get("x-api-key", "")
        if api_key and config.verify_password(api_key):
            return await call_next(request)
        return JSONResponse(status_code=401, content={"detail": "Authentication required"})
    return auth_middleware
