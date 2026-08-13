"""
外部技能 allowlist (data/skills.json) 的唯一读写入口。

目标：
- 所有 API/工具/后台模块读写 skills.json 必须经过此模块，避免多路径写入导致的竞争或格式漂移。
- 写入使用项目统一原子 I/O，并保留可恢复备份。
- 进程内和跨进程读改写都互斥，避免多个 OpenAkita 进程互相覆盖。

返回约定：
- ``external_allowlist is None`` 表示 ``data/skills.json`` 不存在或未声明 allowlist（业务语义：全部启用）。
- ``external_allowlist is set()`` 表示用户显式禁用所有外部技能，或已有文件损坏且无法从备份恢复（安全失败关闭）。

该模块本身**不**触发缓存失效或 agent 通知，调用方需在写入后调用 ``Agent.propagate_skill_change``。
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path

from filelock import FileLock

from openakita.utils.atomic_io import atomic_json_write, read_json_safe

logger = logging.getLogger(__name__)

_WRITE_LOCK = threading.RLock()


def _skills_json_path() -> Path:
    """解析 durable data root 下的 ``skills.json`` 路径。"""
    try:
        from ..config import settings

        return Path(settings.data_dir) / "skills.json"
    except Exception:
        return Path.cwd() / "data" / "skills.json"


def _file_lock(path: Path) -> FileLock:
    return FileLock(str(path) + ".lock")


def _read_config(path: Path) -> dict | None:
    if not path.exists():
        return None
    cfg = read_json_safe(path)
    if cfg is None:
        return None
    if not isinstance(cfg, dict):
        raise ValueError(f"Invalid skills.json root in {path}: expected object")
    return cfg


def read_allowlist() -> tuple[Path, set[str] | None]:
    """读取 ``data/skills.json`` 中的 ``external_allowlist``。

    Returns:
        (path, allowlist) 元组：
        - path: 当前 durable data root 的 skills.json 绝对路径
        - allowlist: 显式 allowlist；文件不存在/未声明时为 ``None``。
          如果已有文件损坏且备份也不可恢复，则返回空集合以 fail-closed。
    """
    path = _skills_json_path()
    if not path.exists():
        return path, None
    try:
        cfg = _read_config(path)
    except (OSError, ValueError) as exc:
        logger.error("Failed to read %s safely: %s", path, exc)
        return path, set()
    if cfg is None:
        logger.error("%s exists but is not recoverable; disabling external skills", path)
        return path, set()
    al = cfg.get("external_allowlist", None)
    if isinstance(al, list):
        return path, {str(x).strip() for x in al if str(x).strip()}
    return path, None


def _atomic_write_json(path: Path, content: dict) -> None:
    """通过统一原子 I/O 写入 JSON，并保留上一版备份。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(
        path,
        content,
        backup=True,
        fsync=True,
        allow_fallback=False,
    )


def _compose_content(allowlist: set[str]) -> dict:
    return {
        "version": 1,
        "external_allowlist": sorted(allowlist),
        "updated_at": datetime.now().isoformat(),
    }


def overwrite_allowlist(allowlist: set[str] | None) -> Path:
    """用完整 allowlist 覆盖 ``data/skills.json``。"""
    path = _skills_json_path()
    final = set(allowlist) if allowlist else set()
    with _WRITE_LOCK, _file_lock(path):
        _atomic_write_json(path, _compose_content(final))
    logger.info("[skills.json] overwrite allowlist (%d ids) -> %s", len(final), path)
    return path


def upsert_skill_ids(skill_ids: set[str]) -> Path | None:
    """原子地把给定 skill_ids 合并进现有 allowlist。

    没有显式 allowlist 时不创建新文件，保持“全部启用”语义。
    已存在但不可恢复的文件会直接报错，避免损坏状态被静默改成更宽权限。
    """
    if not skill_ids:
        return None

    path = _skills_json_path()
    with _WRITE_LOCK, _file_lock(path):
        if not path.exists():
            return None
        cfg = _read_config(path)
        if cfg is None:
            raise OSError(f"skills.json is not recoverable: {path}")

        current = cfg.get("external_allowlist", None)
        if not isinstance(current, list):
            return None

        merged = {str(x).strip() for x in current if str(x).strip()} | {
            s.strip() for s in skill_ids if s and s.strip()
        }
        _atomic_write_json(path, _compose_content(merged))

    logger.info("[skills.json] upsert %d skill id(s): %s", len(skill_ids), sorted(skill_ids))
    return path


def remove_skill_ids(skill_ids: set[str]) -> Path | None:
    """从现有 allowlist 中移除给定 skill_ids（卸载场景）。"""
    if not skill_ids:
        return None

    path = _skills_json_path()
    with _WRITE_LOCK, _file_lock(path):
        if not path.exists():
            return None
        cfg = _read_config(path)
        if cfg is None:
            raise OSError(f"skills.json is not recoverable: {path}")

        current = cfg.get("external_allowlist", None)
        if not isinstance(current, list):
            return None

        remaining = {str(x).strip() for x in current if str(x).strip()} - {
            s.strip() for s in skill_ids if s
        }
        _atomic_write_json(path, _compose_content(remaining))

    logger.info("[skills.json] remove %d skill id(s): %s", len(skill_ids), sorted(skill_ids))
    return path
