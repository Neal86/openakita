"""Build-info endpoint backing the frontend stale-bundle banner.

P-RC-2 commit P2.8 mitigation for Phase 7 in the original revamp
plan (red-prompt cache issues): the frontend embeds ``VITE_BUILD_ID``
at compile time and polls this endpoint every 60s; if the
``build_id`` returned here drifts away from the embedded one, the
SPA shows a sticky "新版本可用，请刷新页面" banner so operators do
not get stuck on a stale bundle after a backend redeploy that also
shipped a new SPA.

The endpoint is intentionally *unauthenticated* and *uncached* --
it is just a few-byte JSON read so the SPA can detect drift without
worrying about login state or stale CDN caches.

Resolution order for ``build_id`` (first non-empty wins):

1. ``OPENAKITA_BUILD_ID`` env var (CI / container override).
2. The ``__version__`` exposed by ``openakita`` package metadata
   (matches ``pyproject.toml``).
3. ``"dev"`` as a last resort.
"""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["构建信息"])


def _resolve_build_id() -> str:
    env = os.environ.get("OPENAKITA_BUILD_ID", "").strip()
    if env:
        return env
    try:
        v = version("openakita")
        if v:
            return v
    except PackageNotFoundError:
        pass
    return "dev"


@router.get("/build-info", summary="后端构建信息（用于前端检测过期 bundle）")
def get_build_info() -> dict[str, str]:
    """Return the running backend's build identifier.

    The frontend polls this every 60s and compares the response
    with its compile-time ``VITE_BUILD_ID``. A drift triggers the
    "请刷新页面" banner.
    """

    return {"build_id": _resolve_build_id()}
