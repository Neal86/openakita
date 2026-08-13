"""OA API for the Windows WeChat Desktop Connector."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import shutil
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from openakita.wechat_desktop import wechat_desktop_manager
from openakita.windows_connector import windows_connector_manager

router = APIRouter(prefix="/api/wechat-desktop")
logger = logging.getLogger(__name__)
RELEASE_FILENAME = "OpenAkita-WeChat-Connector-Windows-x64.zip"
DEFAULT_RELEASE_URL = (
    "https://github.com/Neal86/openakita/releases/download/"
    f"wechat-connector-latest/{RELEASE_FILENAME}"
)
_PAIR_WINDOW_SECONDS = 300
_PAIR_MAX_FAILURES = 10
_pair_failures: dict[str, list[float]] = defaultdict(list)
_pair_lock = asyncio.Lock()
_download_lock = asyncio.Lock()


class PairingCreateRequest(BaseModel):
    node_name: str = Field(default="Windows 微信节点", min_length=1, max_length=100)
    ttl_seconds: int = Field(default=600, ge=60, le=3600)


class PairingConsumeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=20)


class PairingCloseRequest(BaseModel):
    code: str = Field(min_length=6, max_length=20)


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _data_dir() -> Path:
    configured = os.environ.get("OPENAKITA_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    try:
        from openakita.config import settings

        return Path(settings.data_dir).resolve()
    except Exception:
        return Path.home() / ".openakita" / "data"


def _release_cache_path() -> Path:
    return _data_dir() / "releases" / RELEASE_FILENAME


async def _pair_allowed(key: str) -> bool:
    now = time.monotonic()
    async with _pair_lock:
        rows = [
            stamp
            for stamp in _pair_failures.get(key, [])
            if now - stamp < _PAIR_WINDOW_SECONDS
        ]
        if rows:
            _pair_failures[key] = rows
        else:
            _pair_failures.pop(key, None)
        return len(rows) < _PAIR_MAX_FAILURES


async def _record_pair_failure(key: str) -> None:
    now = time.monotonic()
    async with _pair_lock:
        rows = [
            stamp
            for stamp in _pair_failures.get(key, [])
            if now - stamp < _PAIR_WINDOW_SECONDS
        ]
        rows.append(now)
        _pair_failures[key] = rows


async def _clear_pair_failures(key: str) -> None:
    async with _pair_lock:
        _pair_failures.pop(key, None)


@router.get("/nodes")
async def list_nodes() -> dict[str, Any]:
    return {"nodes": await wechat_desktop_manager.list_nodes()}


@router.get("/nodes/{node_id}")
async def get_node(node_id: str) -> dict[str, Any]:
    node = await wechat_desktop_manager.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Windows 微信节点不存在")
    return node


@router.delete("/nodes/{node_id}")
async def delete_node(node_id: str) -> dict[str, bool]:
    grants = await windows_connector_manager.list_grants(node_id)
    if not await wechat_desktop_manager.revoke_node(node_id):
        raise HTTPException(status_code=404, detail="Windows 微信节点不存在")
    for grant in grants:
        grant_id = str(grant.get("id") or "")
        if grant_id:
            await windows_connector_manager.delete_grant(grant_id)
    await windows_connector_manager.sync_resources(node_id, [])
    return {"ok": True}


@router.post("/pairing-code")
async def create_pairing_code(body: PairingCreateRequest) -> dict[str, Any]:
    code = await wechat_desktop_manager.create_pairing_code(
        body.node_name, body.ttl_seconds
    )
    return {"code": code, "expires_in": body.ttl_seconds}


@router.post("/pairing-code/close")
async def close_pairing_code(body: PairingCloseRequest) -> dict[str, bool]:
    return {
        "ok": True,
        "closed": await wechat_desktop_manager.cancel_pairing_code(body.code),
    }


@router.post("/pair")
async def pair_connector(
    body: PairingConsumeRequest, request: Request
) -> dict[str, str]:
    key = _client_key(request)
    if not await _pair_allowed(key):
        raise HTTPException(status_code=429, detail="配对失败次数过多，请稍后再试")
    try:
        node_id, node_token, node_name = await wechat_desktop_manager.consume_pairing_code(
            body.code
        )
    except ValueError as exc:
        await _record_pair_failure(key)
        raise HTTPException(status_code=400, detail="配对码无效或已过期") from exc
    await _clear_pair_failures(key)
    return {"node_id": node_id, "node_token": node_token, "node_name": node_name}


@router.get("/delivery/{request_id}")
async def get_delivery(request_id: str) -> dict[str, Any]:
    receipt = await wechat_desktop_manager.get_delivery_receipt(request_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="发送记录不存在")
    return receipt


def _is_valid_release_zip(path: Path | None) -> bool:
    if path is None or not path.is_file():
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            return bool(archive.namelist()) and archive.testzip() is None
    except (OSError, zipfile.BadZipFile):
        return False


def _local_release_path() -> Path | None:
    configured = os.environ.get("OPENAKITA_WECHAT_CONNECTOR_PACKAGE", "").strip()
    candidates = [
        Path(configured).expanduser() if configured else None,
        _release_cache_path(),
        Path(__file__).resolve().parents[4] / "dist" / RELEASE_FILENAME,
    ]
    return next((path for path in candidates if _is_valid_release_zip(path)), None)


def _download_release_to_cache() -> Path:
    url = os.environ.get(
        "OPENAKITA_WECHAT_CONNECTOR_DOWNLOAD_URL", DEFAULT_RELEASE_URL
    ).strip()
    cache = _release_cache_path()
    cache.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix="wechat-desktop-connector-",
        suffix=".zip",
        dir=str(cache.parent),
    )
    os.close(fd)
    temp = Path(temp_name)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "OpenAkita-WeChat-Connector-Downloader/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temp.open(
            "wb"
        ) as out:  # noqa: S310
            shutil.copyfileobj(response, out, length=1024 * 1024)
        if temp.stat().st_size <= 0:
            raise OSError("downloaded connector package is empty")
        try:
            with zipfile.ZipFile(temp) as archive:
                if not archive.namelist():
                    raise OSError("downloaded connector package has no files")
                bad_member = archive.testzip()
                if bad_member is not None:
                    raise OSError(
                        f"downloaded connector package failed CRC validation: {bad_member}"
                    )
        except zipfile.BadZipFile as exc:
            raise OSError("downloaded connector package is not a valid ZIP archive") from exc
        os.replace(temp, cache)
        return cache
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


@router.get("/connector/download", response_model=None)
async def download_connector() -> FileResponse:
    local_path = _local_release_path()
    if local_path is None:
        async with _download_lock:
            local_path = _local_release_path()
            if local_path is None:
                try:
                    local_path = await asyncio.to_thread(_download_release_to_cache)
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    raise HTTPException(
                        status_code=503,
                        detail="Windows Connector 发布包尚未生成或暂时无法下载",
                    ) from exc
    return FileResponse(
        local_path,
        media_type="application/zip",
        filename=RELEASE_FILENAME,
        headers={"Cache-Control": "no-store"},
    )


def _configured_bots_for_node(node_id: str) -> list[dict[str, Any]]:
    try:
        from openakita.config import settings

        result: list[dict[str, Any]] = []
        for raw in getattr(settings, "im_bots", []) or []:
            if not isinstance(raw, dict) or raw.get("type") != "wechat_desktop":
                continue
            if raw.get("enabled", True) is False:
                continue
            creds = raw.get("credentials") or {}
            if not isinstance(creds, dict) or str(creds.get("node_id") or "") != node_id:
                continue
            result.append(
                {
                    "version": 1,
                    "event": "config.sync",
                    "bot_id": str(raw.get("id") or ""),
                    "payload": {
                        "wechat_account_id": str(creds.get("wechat_account_id") or ""),
                        "allowed_groups": creds.get("allowed_groups") or [],
                        "allowed_contacts": creds.get("allowed_contacts") or [],
                        "ignore_senders": creds.get("ignore_senders") or [],
                        "mention_only": bool(creds.get("mention_only", False)),
                        "private_chat_enabled": bool(
                            creds.get("private_chat_enabled", False)
                        ),
                        "auto_reply": bool(creds.get("auto_reply", True)),
                        "human_takeover": bool(creds.get("human_takeover", False)),
                        "merge_window_seconds": int(
                            creds.get("merge_window_seconds", 2)
                        ),
                        "send_interval_seconds": int(
                            creds.get("send_interval_seconds", 3)
                        ),
                        "duplicate_ttl_seconds": int(
                            creds.get("duplicate_ttl_seconds", 600)
                        ),
                    },
                }
            )
        return result
    except Exception:
        return []


async def _send_event_error(websocket: WebSocket, event: str, exc: Exception) -> None:
    try:
        await websocket.send_json(
            {
                "event": "error",
                "source_event": event,
                "detail": str(exc),
                "error_type": type(exc).__name__,
            }
        )
    except Exception:
        pass


@router.websocket("/ws")
async def connector_websocket(websocket: WebSocket) -> None:
    node_id = websocket.query_params.get("node_id", "")
    node_token = websocket.query_params.get("token", "")
    connector_version = websocket.query_params.get("version", "")
    if not node_id or not node_token:
        await websocket.close(code=4401, reason="missing connector credentials")
        return
    if not await wechat_desktop_manager.authenticate_node(node_id, node_token):
        await websocket.close(code=4403, reason="invalid connector credentials")
        return

    await websocket.accept()
    connection_id = secrets.token_hex(12)

    async def send(payload: dict[str, Any]) -> None:
        await websocket.send_json(payload)

    await wechat_desktop_manager.attach_node(
        node_id,
        node_token=node_token,
        send=send,
        connector_version=connector_version,
        connection_id=connection_id,
    )
    await windows_connector_manager.begin_remote_connection(node_id, connection_id)

    try:
        await websocket.send_json(
            {"version": 1, "event": "node.ready", "node_id": node_id}
        )
        for command in _configured_bots_for_node(node_id):
            await websocket.send_json(command)
        for command in await windows_connector_manager.commands_for_attach(node_id):
            await websocket.send_json(command)

        while True:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                break
            try:
                envelope = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"event": "error", "detail": "invalid JSON"})
                continue
            if not isinstance(envelope, dict):
                await websocket.send_json(
                    {"event": "error", "detail": "envelope must be an object"}
                )
                continue

            event = str(envelope.get("event") or "")
            payload = envelope.get("payload") or {}
            if not isinstance(payload, dict):
                payload = {}
            try:
                await wechat_desktop_manager.assert_current_connection(
                    node_id, connection_id
                )
                if event == "node.heartbeat":
                    await wechat_desktop_manager.heartbeat(
                        node_id, connection_id=connection_id
                    )
                elif event == "windows.resources.sync":
                    await windows_connector_manager.sync_resources(
                        node_id,
                        payload.get("resources") or [],
                        connection_id=connection_id,
                    )
                elif event == "windows.command.result":
                    request_id = str(
                        envelope.get("request_id")
                        or payload.get("request_id")
                        or ""
                    )
                    if request_id:
                        await windows_connector_manager.handle_result(
                            node_id,
                            request_id,
                            payload,
                            connection_id=connection_id,
                        )
                elif event == "wechat.accounts.sync":
                    await wechat_desktop_manager.sync_accounts(
                        node_id,
                        payload.get("accounts") or [],
                        connection_id=connection_id,
                    )
                elif event == "wechat.conversations.sync":
                    await wechat_desktop_manager.sync_conversations(
                        node_id,
                        str(payload.get("wechat_account_id") or ""),
                        groups=payload.get("groups") or [],
                        contacts=payload.get("contacts") or [],
                        connection_id=connection_id,
                    )
                elif event == "wechat.message.received":
                    bot_id = str(
                        envelope.get("bot_id") or payload.get("bot_id") or ""
                    )
                    if not bot_id:
                        raise ValueError("bot_id is required")
                    await wechat_desktop_manager.dispatch_inbound(
                        node_id, bot_id, payload
                    )
                elif event in {
                    "wechat.message.accepted",
                    "wechat.message.sent",
                    "wechat.message.failed",
                }:
                    await wechat_desktop_manager.update_delivery_receipt(
                        request_id=str(
                            envelope.get("request_id")
                            or payload.get("request_id")
                            or ""
                        ),
                        bot_id=str(
                            envelope.get("bot_id") or payload.get("bot_id") or ""
                        ),
                        node_id=node_id,
                        status=event.rsplit(".", 1)[-1],
                        detail=str(payload.get("detail") or ""),
                    )
                elif event == "config.applied":
                    continue
                else:
                    raise ValueError(f"unsupported event: {event}")
            except (ValueError, PermissionError, ConnectionError, KeyError, TypeError) as exc:
                logger.warning(
                    "Desktop connector event rejected: node=%s event=%s error=%s",
                    node_id,
                    event,
                    exc,
                )
                await _send_event_error(websocket, event, exc)
    except WebSocketDisconnect:
        pass
    finally:
        await windows_connector_manager.end_remote_connection(node_id, connection_id)
        await wechat_desktop_manager.detach_node(
            node_id, connection_id=connection_id
        )
