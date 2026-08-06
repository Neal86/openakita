"""OA API for the Windows WeChat Desktop Connector."""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from openakita.wechat_desktop import wechat_desktop_manager

router = APIRouter(prefix="/api/wechat-desktop")
RELEASE_FILENAME = "OpenAkita-WeChat-Connector-Windows-x64.zip"
DEFAULT_RELEASE_URL = (
    "https://github.com/Neal86/openakita/releases/download/"
    f"wechat-connector-latest/{RELEASE_FILENAME}"
)


class PairingCreateRequest(BaseModel):
    node_name: str = Field(default="Windows 微信节点", min_length=1, max_length=100)
    ttl_seconds: int = Field(default=600, ge=60, le=3600)


class PairingConsumeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=20)


class PairingCloseRequest(BaseModel):
    code: str = Field(min_length=6, max_length=20)


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
    if not await wechat_desktop_manager.revoke_node(node_id):
        raise HTTPException(status_code=404, detail="Windows 微信节点不存在")
    return {"ok": True}


@router.post("/pairing-code")
async def create_pairing_code(body: PairingCreateRequest) -> dict[str, Any]:
    code = await wechat_desktop_manager.create_pairing_code(body.node_name, body.ttl_seconds)
    return {"code": code, "expires_in": body.ttl_seconds}


@router.post("/pairing-code/close")
async def close_pairing_code(body: PairingCloseRequest) -> dict[str, bool]:
    return {"ok": True, "closed": await wechat_desktop_manager.cancel_pairing_code(body.code)}


@router.post("/pair")
async def pair_connector(body: PairingConsumeRequest) -> dict[str, str]:
    try:
        node_id, node_token, node_name = await wechat_desktop_manager.consume_pairing_code(body.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="配对码无效或已过期") from exc
    return {"node_id": node_id, "node_token": node_token, "node_name": node_name}


@router.get("/delivery/{request_id}")
async def get_delivery(request_id: str) -> dict[str, Any]:
    receipt = await wechat_desktop_manager.get_delivery_receipt(request_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="发送记录不存在")
    return receipt


def _local_release_path() -> Path | None:
    configured = os.environ.get("OPENAKITA_WECHAT_CONNECTOR_PACKAGE", "").strip()
    candidates = [
        Path(configured) if configured else None,
        Path("data/releases") / RELEASE_FILENAME,
        Path(__file__).resolve().parents[4] / "dist" / RELEASE_FILENAME,
    ]
    return next((path for path in candidates if path and path.is_file()), None)


def _download_release_bytes() -> bytes:
    url = os.environ.get("OPENAKITA_WECHAT_CONNECTOR_DOWNLOAD_URL", DEFAULT_RELEASE_URL).strip()
    request = urllib.request.Request(url, headers={"User-Agent": "OpenAkita-WeChat-Connector-Downloader/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed/admin configured URL
        return response.read()


@router.get("/connector/download", response_model=None)
async def download_connector() -> FileResponse | StreamingResponse:
    local_path = _local_release_path()
    if local_path is not None:
        return FileResponse(
            local_path,
            media_type="application/zip",
            filename=RELEASE_FILENAME,
            headers={"Cache-Control": "no-store"},
        )
    try:
        payload = await asyncio.to_thread(_download_release_bytes)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Windows Connector 发布包尚未生成或暂时无法下载") from exc
    return StreamingResponse(
        iter([payload]),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{RELEASE_FILENAME}"',
            "Cache-Control": "no-store",
            "Content-Length": str(len(payload)),
        },
    )


def _configured_bots_for_node(node_id: str) -> list[dict[str, Any]]:
    """Read persisted OA Bot configuration and return this node's enabled desktop Bots."""
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
                        "private_chat_enabled": bool(creds.get("private_chat_enabled", False)),
                        "auto_reply": bool(creds.get("auto_reply", True)),
                        "human_takeover": bool(creds.get("human_takeover", False)),
                        "merge_window_seconds": int(creds.get("merge_window_seconds", 2)),
                        "send_interval_seconds": int(creds.get("send_interval_seconds", 3)),
                        "duplicate_ttl_seconds": int(creds.get("duplicate_ttl_seconds", 600)),
                    },
                }
            )
        return result
    except Exception:
        return []


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

    async def send(payload: dict[str, Any]) -> None:
        await websocket.send_json(payload)

    await wechat_desktop_manager.attach_node(
        node_id,
        node_token=node_token,
        send=send,
        connector_version=connector_version,
    )
    await websocket.send_json({"version": 1, "event": "node.ready", "node_id": node_id})
    for command in _configured_bots_for_node(node_id):
        await websocket.send_json(command)

    try:
        while True:
            try:
                envelope = json.loads(await websocket.receive_text())
            except json.JSONDecodeError:
                await websocket.send_json({"event": "error", "detail": "invalid JSON"})
                continue
            event = str(envelope.get("event") or "")
            payload = envelope.get("payload") or {}
            if not isinstance(payload, dict):
                payload = {}
            if event == "node.heartbeat":
                await wechat_desktop_manager.heartbeat(node_id)
            elif event == "wechat.accounts.sync":
                await wechat_desktop_manager.sync_accounts(node_id, payload.get("accounts") or [])
            elif event == "wechat.conversations.sync":
                await wechat_desktop_manager.sync_conversations(
                    node_id,
                    str(payload.get("wechat_account_id") or ""),
                    groups=payload.get("groups") or [],
                    contacts=payload.get("contacts") or [],
                )
            elif event == "wechat.message.received":
                bot_id = str(envelope.get("bot_id") or payload.get("bot_id") or "")
                if bot_id:
                    await wechat_desktop_manager.dispatch_inbound(bot_id, payload)
            elif event in {"wechat.message.accepted", "wechat.message.sent", "wechat.message.failed"}:
                await wechat_desktop_manager.update_delivery_receipt(
                    request_id=str(envelope.get("request_id") or payload.get("request_id") or ""),
                    bot_id=str(envelope.get("bot_id") or payload.get("bot_id") or ""),
                    node_id=node_id,
                    status=event.rsplit(".", 1)[-1],
                    detail=str(payload.get("detail") or ""),
                )
            elif event == "config.applied":
                continue
            else:
                await websocket.send_json({"event": "error", "detail": f"unsupported event: {event}"})
    except WebSocketDisconnect:
        pass
    finally:
        await wechat_desktop_manager.detach_node(node_id)
