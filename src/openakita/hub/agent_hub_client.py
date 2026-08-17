"""
AgentHubClient — 与 OpenAkita Platform Agent Store 交互的客户端

功能：
- search: 搜索平台上的 Agent
- get_detail: 获取 Agent 详情
- download: 下载 .akita-agent 包并返回本地路径
- publish: 上传本地 Agent 到平台
- rate: 为 Agent 评分
"""

from __future__ import annotations

import logging
import os
import re
import secrets
from pathlib import Path
from typing import Any

import httpx

from ..config import settings
from ..agents.manifest import MAX_PACKAGE_SIZE

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
DOWNLOAD_TIMEOUT = 120.0
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class AgentHubClient:
    """Agent Store HTTP 客户端"""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.hub_api_url).rstrip("/")
        self._client: httpx.AsyncClient | None = None

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"User-Agent": f"OpenAkita/{self._get_version()}"}
        if settings.hub_api_key:
            headers["X-Akita-Key"] = settings.hub_api_key
        if settings.hub_device_id:
            headers["X-Akita-Device"] = settings.hub_device_id
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=DEFAULT_TIMEOUT,
                headers=self._auth_headers(),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _get_version() -> str:
        try:
            from .._bundled_version import __version__

            return __version__
        except Exception:
            return "dev"

    async def search(
        self,
        query: str = "",
        category: str = "",
        sort: str = "downloads",
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        client = await self._get_client()
        params: dict[str, Any] = {"page": str(page), "limit": str(limit), "sort": sort}
        if query:
            params["q"] = query
        if category:
            params["category"] = category

        resp = await client.get("/agents", params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_detail(self, agent_id: str) -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.get(f"/agents/{agent_id}")
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _safe_package_filename(agent_id: str) -> str:
        safe_id = _SAFE_FILENAME.sub("-", str(agent_id or "").strip()).strip(".-_")
        if not safe_id:
            safe_id = f"agent-{secrets.token_hex(6)}"
        return f"{safe_id[:128]}.akita-agent"

    async def download(self, agent_id: str, save_dir: Path | None = None) -> Path:
        """Download an Agent package to the durable data root.

        The remote ``Content-Disposition`` filename is intentionally ignored:
        Hub metadata is untrusted input and must never be allowed to select a
        filesystem path. The response is streamed with a strict package-size
        limit so a broken or hostile Hub cannot exhaust process memory or disk.
        """
        client = await self._get_client()
        if save_dir is None:
            save_dir = Path(settings.data_dir) / "agent_packages"
        save_dir = Path(save_dir).expanduser().resolve()
        save_dir.mkdir(parents=True, exist_ok=True)

        file_path = save_dir / self._safe_package_filename(agent_id)
        temp_path = save_dir / f".{file_path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
        total = 0
        try:
            async with client.stream(
                "GET",
                f"/agents/{agent_id}/download",
                follow_redirects=True,
                timeout=DOWNLOAD_TIMEOUT,
            ) as resp:
                resp.raise_for_status()
                declared = resp.headers.get("content-length")
                if declared:
                    try:
                        declared_size = int(declared)
                    except ValueError:
                        declared_size = 0
                    if declared_size > MAX_PACKAGE_SIZE:
                        raise ValueError(
                            f"Agent package exceeds safety limit: {declared_size} bytes"
                        )

                with temp_path.open("wb") as out:
                    async for chunk in resp.aiter_bytes(1024 * 1024):
                        total += len(chunk)
                        if total > MAX_PACKAGE_SIZE:
                            raise ValueError(
                                f"Agent package exceeds safety limit: {total} bytes"
                            )
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())

            if total <= 0:
                raise ValueError("Downloaded Agent package is empty")
            os.replace(temp_path, file_path)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

        logger.info("Downloaded agent package: %s (%d bytes)", file_path, total)
        return file_path

    async def publish(
        self,
        package_path: Path,
        token: str,
        description: str = "",
        category: str = "general",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """上传 .akita-agent 包到平台"""
        client = await self._get_client()
        with open(package_path, "rb") as f:
            files = {"package": (package_path.name, f, "application/zip")}
            data: dict[str, str] = {"category": category}
            if description:
                data["description"] = description
            if tags:
                data["tags"] = ",".join(tags)

            resp = await client.post(
                "/agents",
                files=files,
                data=data,
                headers={"Authorization": f"Bearer {token}"},
                timeout=DOWNLOAD_TIMEOUT,
            )
        resp.raise_for_status()
        return resp.json()

    async def rate(
        self, agent_id: str, score: int, comment: str = "", token: str = ""
    ) -> dict[str, Any]:
        client = await self._get_client()
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        resp = await client.post(
            f"/agents/{agent_id}/rate",
            json={"score": score, "comment": comment},
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()

    async def get_categories(self) -> list[dict[str, Any]]:
        client = await self._get_client()
        resp = await client.get("/agents", params={"limit": "0"})
        resp.raise_for_status()
        data = resp.json()
        return data.get("categories", [])
