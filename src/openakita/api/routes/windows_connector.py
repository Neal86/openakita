from __future__ import annotations

import asyncio
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from openakita.wechat_desktop import wechat_desktop_manager
from openakita.windows_connector import windows_connector_manager

router = APIRouter(prefix="/api/windows-connector", tags=["Windows Connector"])
RELEASE_FILENAME = "OpenAkita-Windows-Connector-Windows-x64.zip"
DEFAULT_RELEASE_URL = (
    "https://github.com/Neal86/openakita/releases/download/"
    f"wechat-connector-latest/{RELEASE_FILENAME}"
)


class GrantPayload(BaseModel):
    id: str | None = None
    node_id: str
    agent_profile_id: str
    resource_id: str
    remark: str = ""
    permissions: dict[str, bool] = Field(default_factory=dict)


class RemarkPayload(BaseModel):
    remark: str = ""


class ExecutePayload(BaseModel):
    node_id: str
    agent_profile_id: str
    resource_id: str
    action: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=60, ge=1, le=300)


@router.get("/nodes")
async def list_nodes() -> dict[str, Any]:
    nodes = await wechat_desktop_manager.list_nodes()
    for node in nodes:
        node["resources"] = await windows_connector_manager.list_resources(node["id"])
        node["grants"] = await windows_connector_manager.list_grants(node["id"])
    return {"nodes": nodes}


@router.get("/nodes/{node_id}/resources")
async def list_resources(node_id: str) -> dict[str, Any]:
    node = await wechat_desktop_manager.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Windows Connector 节点不存在")
    return {"resources": await windows_connector_manager.list_resources(node_id)}


@router.post("/nodes/{node_id}/refresh")
async def refresh_resources(node_id: str) -> dict[str, bool]:
    try:
        await wechat_desktop_manager.send_command(
            node_id,
            {"version": 1, "event": "windows.resources.refresh", "payload": {}},
        )
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/grants")
async def list_grants(node_id: str | None = None) -> dict[str, Any]:
    return {"grants": await windows_connector_manager.list_grants(node_id)}


@router.post("/grants")
async def save_grant(body: GrantPayload) -> dict[str, Any]:
    try:
        grant = await windows_connector_manager.upsert_grant(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"grant": grant}


@router.put("/grants/{grant_id}/remark")
async def update_remark(grant_id: str, body: RemarkPayload) -> dict[str, Any]:
    try:
        grant = await windows_connector_manager.set_remark(grant_id, body.remark)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="授权不存在") from exc
    return {"grant": grant}


@router.delete("/grants/{grant_id}")
async def delete_grant(grant_id: str) -> dict[str, bool]:
    if not await windows_connector_manager.delete_grant(grant_id):
        raise HTTPException(status_code=404, detail="授权不存在")
    return {"deleted": True}


@router.post("/execute")
async def execute(body: ExecutePayload) -> dict[str, Any]:
    try:
        return await windows_connector_manager.execute(
            node_id=body.node_id,
            agent_profile_id=body.agent_profile_id,
            resource_id=body.resource_id,
            action=body.action,
            arguments=body.arguments,
            timeout=float(body.timeout_seconds),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Windows Connector 命令超时") from exc


def _local_release_path() -> Path | None:
    configured = os.environ.get("OPENAKITA_WINDOWS_CONNECTOR_PACKAGE", "").strip()
    candidates = [
        Path(configured) if configured else None,
        Path("data/releases") / RELEASE_FILENAME,
        Path(__file__).resolve().parents[4] / "dist" / RELEASE_FILENAME,
    ]
    return next((path for path in candidates if path and path.is_file()), None)


def _download_release_bytes() -> bytes:
    url = os.environ.get("OPENAKITA_WINDOWS_CONNECTOR_DOWNLOAD_URL", DEFAULT_RELEASE_URL).strip()
    request = urllib.request.Request(url, headers={"User-Agent": "OpenAkita-Windows-Connector-Downloader/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - admin-configured release URL
        return response.read()


@router.get("/connector/download", response_model=None)
async def download_connector() -> FileResponse | StreamingResponse:
    local = _local_release_path()
    if local is not None:
        return FileResponse(local, media_type="application/zip", filename=RELEASE_FILENAME, headers={"Cache-Control": "no-store"})
    try:
        payload = await asyncio.to_thread(_download_release_bytes)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Windows Connector 发布包尚未生成或暂时无法下载") from exc
    try:
        cache = Path("data/releases") / RELEASE_FILENAME
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        tmp.write_bytes(payload)
        tmp.replace(cache)
    except OSError:
        pass
    return StreamingResponse(
        iter([payload]),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{RELEASE_FILENAME}"',
            "Cache-Control": "no-store",
            "Content-Length": str(len(payload)),
        },
    )
