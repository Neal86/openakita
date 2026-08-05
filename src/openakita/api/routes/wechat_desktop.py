"""OA API for the Windows WeChat Desktop Connector."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from openakita.wechat_desktop import wechat_desktop_manager

router = APIRouter(prefix="/api/wechat-desktop")


class PairingCreateRequest(BaseModel):
    node_name: str = Field(default="Windows 微信节点", min_length=1, max_length=100)
    ttl_seconds: int = Field(default=600, ge=60, le=3600)


class PairingConsumeRequest(BaseModel):
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
    removed = await wechat_desktop_manager.revoke_node(node_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Windows 微信节点不存在")
    return {"ok": True}


@router.post("/pairing-code")
async def create_pairing_code(body: PairingCreateRequest) -> dict[str, Any]:
    code = await wechat_desktop_manager.create_pairing_code(
        body.node_name,
        ttl_seconds=body.ttl_seconds,
    )
    return {"code": code, "expires_in": body.ttl_seconds}


@router.post("/pair")
async def pair_connector(body: PairingConsumeRequest) -> dict[str, str]:
    try:
        node_id, node_token, node_name = await wechat_desktop_manager.consume_pairing_code(
            body.code
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="配对码无效或已过期") from exc
    return {"node_id": node_id, "node_token": node_token, "node_name": node_name}


@router.get("/delivery/{request_id}")
async def get_delivery(request_id: str) -> dict[str, Any]:
    receipt = await wechat_desktop_manager.get_delivery_receipt(request_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="发送记录不存在")
    return receipt


def _connector_bundle_root() -> Path:
    package_root = Path(__file__).resolve().parents[2] / "wechat_desktop" / "connector_bundle"
    if package_root.is_dir():
        return package_root
    source_root = Path(__file__).resolve().parents[4] / "apps" / "wechat-connector"
    return source_root


@router.get("/connector/download")
async def download_connector(request: Request) -> StreamingResponse:
    """Download the Windows connector as a self-contained ZIP bundle."""
    root = _connector_bundle_root()
    if not root.is_dir():
        raise HTTPException(status_code=503, detail="Windows Connector 安装包尚未生成")

    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, Path("OpenAkita-WeChat-Connector") / path.relative_to(root))
    memory.seek(0)
    headers = {
        "Content-Disposition": 'attachment; filename="OpenAkita-WeChat-Connector.zip"',
        "Cache-Control": "no-store",
    }
    return StreamingResponse(memory, media_type="application/zip", headers=headers)


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

    try:
        while True:
            message = await websocket.receive_text()
            try:
                envelope = json.loads(message)
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
            else:
                await websocket.send_json({"event": "error", "detail": f"unsupported event: {event}"})
    except WebSocketDisconnect:
        pass
    finally:
        await wechat_desktop_manager.detach_node(node_id)
