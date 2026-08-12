from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from openakita.wechat_desktop import wechat_desktop_manager
from openakita.windows_connector import windows_connector_manager
from openakita.windows_connector.manager import LOCAL_NODE_ID
from openakita.windows_connector.preview import preview_focus_resource

router = APIRouter(prefix="/api/windows-connector", tags=["Windows Connector"])
RELEASE_FILENAME = "OpenAkita-Windows-Connector-Windows-x64.zip"
DEFAULT_RELEASE_URL = (
    "https://github.com/Neal86/openakita/releases/download/"
    f"windows-connector-latest/{RELEASE_FILENAME}"
)
_PAIR_WINDOW_SECONDS = 300
_PAIR_MAX_FAILURES = 10
_pair_failures: dict[str, list[float]] = defaultdict(list)
_pair_lock = asyncio.Lock()
_download_lock = asyncio.Lock()


class PairingCreatePayload(BaseModel):
    node_name: str = Field(default="Windows 电脑", min_length=1, max_length=100)
    ttl_seconds: int = Field(default=3600, ge=60, le=3600)


class PairingConsumePayload(BaseModel):
    code: str = Field(min_length=6, max_length=20)


class PairingClosePayload(BaseModel):
    code: str = Field(min_length=6, max_length=20)


class GrantPayload(BaseModel):
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


class PreviewFocusPayload(BaseModel):
    node_id: str
    resource_id: str


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _data_dir() -> Path:
    configured = os.environ.get("OPENAKITA_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
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


@router.post("/pairing-code")
async def create_pairing_code(body: PairingCreatePayload) -> dict[str, Any]:
    code = await wechat_desktop_manager.create_pairing_code(
        body.node_name, body.ttl_seconds
    )
    return {"code": code, "expires_in": body.ttl_seconds}


@router.post("/pairing-code/close")
async def close_pairing_code(body: PairingClosePayload) -> dict[str, bool]:
    return {
        "ok": True,
        "closed": await wechat_desktop_manager.cancel_pairing_code(body.code),
    }


@router.post("/pair")
async def pair_connector(
    body: PairingConsumePayload, request: Request
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


@router.get("/nodes")
async def list_nodes(refresh_local: bool = False) -> dict[str, Any]:
    """Return cached state by default; discovery is explicit to keep polling cheap."""
    local = await windows_connector_manager.local_node(refresh=refresh_local)
    remote_nodes = await wechat_desktop_manager.list_nodes()
    nodes = [local]
    for node in remote_nodes:
        if node.get("id") == LOCAL_NODE_ID:
            continue
        node["transport"] = "remote"
        node["embedded"] = False
        node["resources"] = await windows_connector_manager.list_resources(node["id"])
        node["grants"] = await windows_connector_manager.list_grants(node["id"])
        nodes.append(node)
    return {"nodes": nodes}


@router.get("/nodes/{node_id}/resources")
async def list_resources(node_id: str, refresh: bool = False) -> dict[str, Any]:
    if node_id == LOCAL_NODE_ID:
        resources = (
            await windows_connector_manager.refresh_local_resources()
            if refresh
            else await windows_connector_manager.list_resources(LOCAL_NODE_ID)
        )
        return {"resources": resources}
    node = await wechat_desktop_manager.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Windows Connector 节点不存在")
    return {"resources": await windows_connector_manager.list_resources(node_id)}


@router.post("/nodes/{node_id}/refresh")
async def refresh_resources(node_id: str) -> dict[str, bool]:
    if node_id == LOCAL_NODE_ID:
        await windows_connector_manager.refresh_local_resources()
        return {"ok": True}
    try:
        await wechat_desktop_manager.send_command(
            node_id,
            {"version": 1, "event": "windows.resources.refresh", "payload": {}},
        )
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/preview-focus")
async def preview_focus(body: PreviewFocusPayload) -> dict[str, Any]:
    """Focus a discovered target so the operator can verify it before granting it.

    Preview focus is deliberately limited to foreground/tab activation. It
    cannot click, type, navigate, launch or close anything, and it never creates
    or changes an Agent permission grant.
    """
    resources = await windows_connector_manager.list_resources(body.node_id)
    if not any(str(row.get("id") or "") == body.resource_id for row in resources):
        raise HTTPException(status_code=404, detail="Windows 目标已离线，请重新扫描应用")

    if body.node_id == LOCAL_NODE_ID:
        try:
            result = await asyncio.to_thread(
                preview_focus_resource,
                windows_connector_manager._local_executor,  # noqa: SLF001 - operator preview uses embedded executor
                body.resource_id,
            )
        except (PermissionError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True, "result": result, "delivered": True}

    try:
        await wechat_desktop_manager.send_command(
            body.node_id,
            {
                "version": 1,
                "event": "windows.preview.focus",
                "payload": {"resource_id": body.resource_id},
            },
        )
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "delivered": True}


@router.get("/grants")
async def list_grants(node_id: str | None = None) -> dict[str, Any]:
    return {"grants": await windows_connector_manager.list_grants(node_id)}


@router.post("/grants")
async def save_grant(body: GrantPayload) -> dict[str, Any]:
    from openakita.agents.profile import agent_profile_exists

    if not agent_profile_exists(body.agent_profile_id):
        raise HTTPException(status_code=404, detail="Agent profile not found")
    try:
        grant = await windows_connector_manager.upsert_grant(body.model_dump())
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
    from openakita.agents.profile import agent_profile_exists

    if not agent_profile_exists(body.agent_profile_id):
        raise HTTPException(status_code=404, detail="Agent profile not found")
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
        Path(configured).expanduser() if configured else None,
        _release_cache_path(),
        Path(__file__).resolve().parents[4] / "dist" / RELEASE_FILENAME,
    ]
    return next((path for path in candidates if path and path.is_file()), None)


def _download_release_to_cache() -> Path:
    url = os.environ.get(
        "OPENAKITA_WINDOWS_CONNECTOR_DOWNLOAD_URL", DEFAULT_RELEASE_URL
    ).strip()
    cache = _release_cache_path()
    cache.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix="windows-connector-",
        suffix=".zip",
        dir=str(cache.parent),
    )
    os.close(fd)
    temp = Path(temp_name)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "OpenAkita-Windows-Connector-Downloader/1.0"},
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
    local = _local_release_path()
    if local is None:
        async with _download_lock:
            local = _local_release_path()
            if local is None:
                try:
                    local = await asyncio.to_thread(_download_release_to_cache)
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    raise HTTPException(
                        status_code=503,
                        detail="Windows Connector 发布包尚未生成或暂时无法下载",
                    ) from exc
    return FileResponse(
        local,
        media_type="application/zip",
        filename=RELEASE_FILENAME,
        headers={"Cache-Control": "no-store"},
    )
