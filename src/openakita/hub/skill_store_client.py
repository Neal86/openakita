"""
SkillStoreClient — 与 OpenAkita Platform Skill Store 交互的客户端

功能：
- search: 搜索平台上的 Skill
- get_detail: 获取 Skill 详情
- install: 通过 installUrl 下载并安装 Skill 到本地
- rate: 为 Skill 评分
- submit_repo: 提交 GitHub 仓库供索引
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import secrets
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from ..agents.manifest import (
    MAX_PACKAGE_SIZE,
    MAX_SINGLE_FILE_SIZE,
    validate_external_skill_source,
    validate_file_safety,
)
from ..agents.manifest import (
    MAX_PACKAGE_SIZE,
    MAX_SINGLE_FILE_SIZE,
    validate_external_skill_source,
    validate_file_safety,
)
from ..agents.manifest import (
    MAX_PACKAGE_SIZE,
    MAX_SINGLE_FILE_SIZE,
    validate_external_skill_source,
    validate_file_safety,
)
from ..config import settings
from ..utils.atomic_io import atomic_json_write, safe_write
from ..utils.atomic_io import atomic_json_write, safe_write
from ..utils.atomic_io import atomic_json_write, safe_write

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0

_RETRY_STATUS_CODES = {500, 502, 503, 504}
_MAX_RETRIES = 3
_BASE_BACKOFF = 1.0
_RATE_LIMIT_BACKOFF = 5.0


async def _retry_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_retries: int = _MAX_RETRIES,
    **kwargs,
) -> httpx.Response:
    """Execute an HTTP request with retry + exponential backoff for 5xx/timeout and 429."""
    last_exc: Exception | None = None
    last_resp: httpx.Response | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = await client.request(method, url, **kwargs)
            last_resp = resp
            if resp.status_code == 429:
                try:
                    retry_after = float(resp.headers.get("Retry-After", _RATE_LIMIT_BACKOFF))
                except (ValueError, TypeError):
                    retry_after = _RATE_LIMIT_BACKOFF
                wait = min(retry_after, 30.0) + random.uniform(0, 1)
                logger.warning("Rate limited (429) on %s, waiting %.1fs", url, wait)
                await asyncio.sleep(wait)
                continue
            if resp.status_code in _RETRY_STATUS_CODES and attempt < max_retries:
                wait = _BASE_BACKOFF * (2**attempt) + random.uniform(0, 0.5)
                logger.warning(
                    "Server error %d on %s, retry %d/%d in %.1fs",
                    resp.status_code,
                    url,
                    attempt + 1,
                    max_retries,
                    wait,
                )
                await asyncio.sleep(wait)
                continue
            return resp
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_exc = e
            if attempt < max_retries:
                wait = _BASE_BACKOFF * (2**attempt) + random.uniform(0, 0.5)
                logger.warning(
                    "Request to %s failed (%s), retry %d/%d in %.1fs",
                    url,
                    type(e).__name__,
                    attempt + 1,
                    max_retries,
                    wait,
                )
                await asyncio.sleep(wait)
            else:
                raise
    if last_resp is not None:
        return last_resp
    if last_exc is None:
        raise RuntimeError("All retry attempts exhausted")
    raise last_exc  # type: ignore[misc]


class SkillStoreClient:
    """Skill Store HTTP 客户端"""

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
        trust_level: str = "",
        sort: str = "installs",
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        client = await self._get_client()
        params: dict[str, Any] = {"page": str(page), "limit": str(limit), "sort": sort}
        if query:
            params["q"] = query
        if category:
            params["category"] = category
        if trust_level:
            params["trustLevel"] = trust_level

        resp = await _retry_request(client, "GET", "/skills", params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_detail(self, skill_id: str) -> dict[str, Any]:
        client = await self._get_client()
        resp = await _retry_request(client, "GET", f"/skills/{skill_id}")
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _write_origin(skill_dir: Path, install_url: str) -> None:
        """Write provenance files to track skill source."""
        try:
            origin = {
                "source": install_url,
                "type": "platform_store",
                "installed_at": datetime.now(UTC).isoformat(),
            }
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                import re

                import yaml

                m = re.match(r"^---\s*\n(.*?)\n---", skill_md.read_text("utf-8"), re.DOTALL)
                if m:
                    fm = yaml.safe_load(m.group(1)) or {}
                    if fm.get("version"):
                        origin["version"] = fm["version"]
            atomic_json_write(
                skill_dir / ".openakita-origin.json",
                origin,
                backup=True,
                fsync=True,
                allow_fallback=False,
            )
            # Also write .openakita-source for compatibility with bridge/frontend matching
            safe_write(
                skill_dir / ".openakita-source",
                install_url,
                backup=True,
                fsync=True,
                allow_fallback=False,
            )
        except Exception as e:
            logger.debug(f"Failed to write origin tracking: {e}")

    async def install_skill(
        self,
        install_url: str,
        target_dir: Path | None = None,
        *,
        skill_id: str | None = None,
    ) -> Path:
        """安装 Skill 到本地

        优先从平台缓存下载 ZIP，失败时 fallback 到 git clone。
        install_url 格式: owner/repo@skill_name 或完整 git URL
        """
        if target_dir is None:
            target_dir = settings.skills_path
        target_dir = Path(target_dir).expanduser().resolve()
        target_dir.mkdir(parents=True, exist_ok=True)

        if not validate_external_skill_source(install_url):
            raise ValueError(f"Unsafe Skill Store install URL: {install_url!r}")

        if "@" in install_url:
            repo_part, skill_name = install_url.rsplit("@", 1)
        else:
            repo_part = install_url
            skill_name = repo_part.rstrip("/").rsplit("/", 1)[-1]
            if skill_name.endswith(".git"):
                skill_name = skill_name[:-4]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", skill_name):
            raise ValueError(f"Unsafe Skill Store skill name: {skill_name!r}")
        if not repo_part.startswith("http"):
            repo_part = f"https://github.com/{repo_part}"

        skill_dir = target_dir / skill_name
        import tempfile

        async def _attempt(strategy: str) -> bool:
            with tempfile.TemporaryDirectory(
                dir=target_dir, prefix=f".{skill_name}.stage-"
            ) as stage_root:
                staging_dir = Path(stage_root) / "skill"
                installed = False
                if strategy == "platform":
                    installed = await self._install_from_platform_cache(
                        str(skill_id or ""), skill_name, staging_dir
                    )
                else:
                    installed = await self._install_via_git(repo_part, skill_name, staging_dir)
                if not installed:
                    return False
                self._write_origin(staging_dir, install_url)
                self._replace_skill_directory(staging_dir, skill_dir)
                return True

        if skill_id:
            try:
                if await _attempt("platform"):
                    logger.info(
                        "Installed skill from platform cache: %s -> %s", skill_name, skill_dir
                    )
                    return skill_dir
            except Exception as e:
                logger.debug("Platform cache download failed for %s: %s", skill_id, e)

        try:
            if await _attempt("git"):
                logger.info("Installed skill via git: %s -> %s", skill_name, skill_dir)
                return skill_dir
        except Exception as e:
            logger.debug("git clone failed for %s: %s", skill_name, e)

        raise RuntimeError(
            f"Failed to install skill '{skill_name}': "
            "neither platform cache nor git clone succeeded"
        )

    async def _install_from_platform_cache(
        self, skill_id: str, skill_name: str, skill_dir: Path
    ) -> bool:
        """Download cached ZIP from platform and extract."""
        import io
        import zipfile

        client = await self._get_client()
        data = bytearray()
        async with client.stream(
            "GET",
            f"/skills/{skill_id}/download",
            follow_redirects=True,
            timeout=60.0,
        ) as resp:
            if resp.status_code != 200:
                return False
            declared = resp.headers.get("content-length")
            if declared:
                try:
                    if int(declared) > MAX_PACKAGE_SIZE:
                        raise RuntimeError("Skill ZIP exceeds safety limit")
                except ValueError:
                    pass
            async for chunk in resp.aiter_bytes(1024 * 1024):
                data.extend(chunk)
                if len(data) > MAX_PACKAGE_SIZE:
                    raise RuntimeError("Skill ZIP exceeds safety limit")

        if len(data) < 22:
            return False

        skill_dir.mkdir(parents=True, exist_ok=True)
        total = 0
        seen: set[str] = set()
        with zipfile.ZipFile(io.BytesIO(bytes(data))) as zf:
            for info in zf.infolist():
                errors = validate_file_safety(info.filename)
                if errors:
                    raise RuntimeError(f"Unsafe Skill ZIP member: {'; '.join(errors)}")
                key = "/".join(
                    part.rstrip(" .").casefold()
                    for part in info.filename.replace("\\", "/").split("/")
                )
                if key in seen:
                    raise RuntimeError(f"Duplicate Skill ZIP member: {info.filename}")
                seen.add(key)
                if info.file_size > MAX_SINGLE_FILE_SIZE:
                    raise RuntimeError(f"Skill ZIP member too large: {info.filename}")
                total += info.file_size
                if total > MAX_PACKAGE_SIZE:
                    raise RuntimeError("Skill ZIP expands beyond safety limit")
                if info.external_attr >> 16 & 0o120000 == 0o120000:
                    raise RuntimeError(f"Skill ZIP symlink not allowed: {info.filename}")
            bad_member = zf.testzip()
            if bad_member is not None:
                raise RuntimeError(f"Corrupt Skill ZIP member: {bad_member}")
            zf.extractall(skill_dir)

        skill_md = skill_dir / "SKILL.md"
        return skill_md.exists()

    @staticmethod
    async def _install_via_git(repo_url: str, skill_name: str, skill_dir: Path) -> bool:
        """Clone from git, handling mono-repo structures.

        Many skill repos (e.g., inference-shell/skills) contain multiple skills
        in subdirectories. After cloning, we search for the skill_name subdirectory
        that contains SKILL.md, and only copy that to the target.

        Falls back to GitHub ZIP download when git is not installed.
        """
        import tempfile

        git_exe = shutil.which("git")

        # When git is not available, try GitHub ZIP download as fallback
        if git_exe is None:
            return await SkillStoreClient._install_via_zip_fallback(repo_url, skill_name, skill_dir)

        extra_kwargs: dict = {}
        if sys.platform == "win32":
            extra_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        tmp_parent = Path(tempfile.mkdtemp(prefix="openakita_skill_"))
        tmp_dir = tmp_parent / "repo"
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [git_exe, "clone", "--depth=1", repo_url, str(tmp_dir)],
                capture_output=True,
                text=True,
                timeout=120,
                **extra_kwargs,
            )
            if result.returncode != 0:
                raise RuntimeError(f"git clone failed: {result.stderr}")

            return SkillStoreClient._extract_skill_from_repo(tmp_dir, skill_name, skill_dir)
        finally:
            shutil.rmtree(str(tmp_parent), ignore_errors=True)

    @staticmethod
    async def _install_via_zip_fallback(repo_url: str, skill_name: str, skill_dir: Path) -> bool:
        """Download repo as ZIP from GitHub Archive API when git is unavailable.

        Mirrors the fallback logic in setup_center/bridge.py._download_github_zip.
        """
        import io
        import re
        import tempfile
        import urllib.request
        import zipfile

        m = re.match(r"https?://github\.com/([^/]+)/([^/.]+)", repo_url)
        if not m:
            raise FileNotFoundError(
                "git not found in PATH, and the repo URL is not a recognized GitHub URL "
                "for ZIP fallback. Please install Git (https://git-scm.com)."
            )

        owner, repo = m.group(1), m.group(2)
        mirrors = [
            "https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip",
            "https://gh-proxy.com/https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip",
            "https://mirror.ghproxy.com/https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip",
            "https://ghproxy.net/https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip",
        ]

        data: bytes | None = None
        last_err: Exception | None = None

        for branch in ("main", "master"):
            if data is not None:
                break
            for tpl in mirrors:
                url = tpl.format(owner=owner, repo=repo, branch=branch)
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "OpenAkita"})
                    def _download() -> bytes:
                        with urllib.request.urlopen(req, timeout=30) as resp:
                            declared = resp.headers.get("Content-Length")
                            if declared:
                                try:
                                    if int(declared) > MAX_PACKAGE_SIZE:
                                        raise RuntimeError("GitHub Skill ZIP exceeds safety limit")
                                except ValueError:
                                    pass
                            payload = resp.read(MAX_PACKAGE_SIZE + 1)
                            if len(payload) > MAX_PACKAGE_SIZE:
                                raise RuntimeError("GitHub Skill ZIP exceeds safety limit")
                            return payload

                    data = await asyncio.to_thread(_download)
                    break
                except Exception as e:
                    last_err = e

        if data is None:
            raise RuntimeError(
                f"Git is not installed, and ZIP download from GitHub also failed "
                f"for {owner}/{repo}. Please install Git or check network. "
                f"(Last error: {last_err})"
            )

        tmp_parent = Path(tempfile.mkdtemp(prefix="openakita_skill_zip_"))
        tmp_dir = tmp_parent / "repo"
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for name in zf.namelist():
                    normalized = os.path.normpath(name)
                    if name.startswith("/") or name.startswith("\\") or normalized.startswith(".."):
                        raise RuntimeError(f"Zip Slip detected: dangerous member '{name}'")
                zf.extractall(tmp_parent)

            children = list(tmp_parent.iterdir())
            extracted = [c for c in children if c.is_dir() and c.name != "repo"]
            if len(extracted) == 1:
                tmp_dir = extracted[0]
            elif tmp_dir.exists():
                pass
            else:
                tmp_dir = tmp_parent

            return SkillStoreClient._extract_skill_from_repo(tmp_dir, skill_name, skill_dir)
        finally:
            shutil.rmtree(str(tmp_parent), ignore_errors=True)

    @staticmethod
    def _replace_skill_directory(staging_dir: Path, target_dir: Path) -> None:
        """Atomically swap a prepared Skill into place and restore on failure."""
        backup_dir = target_dir.with_name(
            f".{target_dir.name}.backup-{secrets.token_hex(8)}"
        )
        had_existing = target_dir.exists()
        if had_existing:
            target_dir.replace(backup_dir)
        try:
            staging_dir.replace(target_dir)
        except Exception:
            if had_existing and backup_dir.exists() and not target_dir.exists():
                backup_dir.replace(target_dir)
            raise
        else:
            if backup_dir.exists():
                shutil.rmtree(backup_dir)

    @staticmethod
    def _copy_skill_tree(source: Path, target: Path) -> None:
        """Copy a Skill tree without following symlinks or oversized payloads."""
        target.mkdir(parents=True, exist_ok=True)
        total = 0
        for item in source.rglob("*"):
            if item.is_symlink():
                raise RuntimeError(f"Skill symlink not allowed: {item}")
            rel = item.relative_to(source)
            dest = target / rel
            if item.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            if not item.is_file():
                continue
            size = item.stat().st_size
            if size > MAX_SINGLE_FILE_SIZE:
                raise RuntimeError(f"Skill file too large: {item}")
            total += size
            if total > MAX_PACKAGE_SIZE:
                raise RuntimeError("Skill tree exceeds safety limit")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with item.open("rb") as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out, length=1024 * 1024)

    @staticmethod
    def _extract_skill_from_repo(tmp_dir: Path, skill_name: str, skill_dir: Path) -> bool:
        """Extract skill directory from a cloned/downloaded repo tree."""
        skill_md_at_root = tmp_dir / "SKILL.md"
        if skill_md_at_root.exists():
            SkillStoreClient._copy_skill_tree(tmp_dir, skill_dir)
            git_dir = skill_dir / ".git"
            if git_dir.exists():
                shutil.rmtree(git_dir)
            return True

        candidates = [
            skill_name,
            f"skills/{skill_name}",
            f"tools/{skill_name}",
            f"packages/{skill_name}",
        ]
        seen: set[str] = set()
        for rel in candidates:
            rel_norm = rel.replace("\\", "/").strip("/")
            if not rel_norm or rel_norm in seen:
                continue
            seen.add(rel_norm)
            candidate = tmp_dir / rel_norm
            if candidate.is_dir() and (candidate / "SKILL.md").exists():
                SkillStoreClient._copy_skill_tree(candidate, skill_dir)
                return True

        for skill_md in tmp_dir.rglob("SKILL.md"):
            if skill_md.parent.name == skill_name:
                SkillStoreClient._copy_skill_tree(skill_md.parent, skill_dir)
                return True

        SkillStoreClient._copy_skill_tree(tmp_dir, skill_dir)
        git_dir = skill_dir / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)
        return True

    async def rate(
        self, skill_id: str, score: int, comment: str = "", token: str = ""
    ) -> dict[str, Any]:
        client = await self._get_client()
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        resp = await _retry_request(
            client,
            "POST",
            f"/skills/{skill_id}/rate",
            json={"score": score, "comment": comment},
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()

    async def submit_repo(self, repo_url: str) -> dict[str, Any]:
        client = await self._get_client()
        resp = await _retry_request(
            client,
            "POST",
            "/skills/submit-repo",
            json={"repoUrl": repo_url},
        )
        resp.raise_for_status()
        return resp.json()
