"""WeChat onboarding routes.

Keeps the existing iLink QR-login endpoints unchanged and mounts the independent
Windows WeChat Desktop Connector API under ``/api/wechat-desktop``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import wechat_desktop

logger = logging.getLogger(__name__)
router = APIRouter(tags=["wechat-onboard"])
router.include_router(wechat_desktop.router, tags=["wechat-desktop"])


class PollRequest(BaseModel):
    qrcode: str


@router.post("/api/wechat/onboard/start")
async def onboard_start():
    """Fetch login QR code. Returns qrcode (identifier) and qrcode_url."""
    try:
        from openakita.setup.wechat_onboard import WeChatOnboard

        ob = WeChatOnboard()
        try:
            result = await ob.fetch_qrcode()
            return JSONResponse(content=result)
        finally:
            await ob.close()
    except Exception as e:
        logger.error(f"WeChat onboard start failed: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/api/wechat/onboard/poll")
async def onboard_poll(body: PollRequest):
    """Poll QR login status once (long-poll)."""
    try:
        from openakita.setup.wechat_onboard import WeChatOnboard

        ob = WeChatOnboard()
        try:
            result = await ob.poll_status(body.qrcode)
            return JSONResponse(content=result)
        finally:
            await ob.close()
    except Exception as e:
        logger.error(f"WeChat onboard poll failed: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})
