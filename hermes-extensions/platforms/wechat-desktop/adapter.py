from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult


def _load_desktop_class():
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "wechat" / "adapter.py",
        here.parents[2] / "hermes-extensions" / "wechat" / "adapter.py",
    ]
    configured = os.getenv("HERMES_EXTENSIONS_PLUGIN_DIR", "").strip()
    if configured:
        candidates.insert(0, Path(configured).expanduser().resolve() / "wechat" / "adapter.py")
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise RuntimeError("Hermes Extensions WeChat automation module is not installed")
    name = "hermes_extensions_wechat_desktop_runtime"
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load WeChat automation module from {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module.WeChatDesktop


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _allowed_chats(config: PlatformConfig) -> set[str]:
    extra = config.extra or {}
    raw = str(extra.get("allowed_chats") or os.getenv("WECHAT_DESKTOP_ALLOWED_CHATS", ""))
    return {item.strip() for item in raw.replace("，", ",").split(",") if item.strip()}


def check_requirements() -> bool:
    try:
        return bool(_load_desktop_class().available())
    except Exception:
        return False


def validate_config(config: PlatformConfig) -> bool:
    del config
    return check_requirements()


def _env_enablement() -> dict[str, Any] | None:
    if not _truthy(os.getenv("WECHAT_DESKTOP_AUTO_ENABLE")):
        return None
    seed: dict[str, Any] = {}
    allowed = os.getenv("WECHAT_DESKTOP_ALLOWED_CHATS", "").strip()
    if allowed:
        seed["allowed_chats"] = allowed
    home = os.getenv("WECHAT_DESKTOP_HOME_CHAT", "").strip()
    if home:
        seed["home_channel"] = {"chat_id": home, "name": home}
    return seed


class WeChatDesktopPlatformAdapter(BasePlatformAdapter):
    """Poll unread desktop conversations and route new text into Hermes Gateway."""

    def __init__(self, config: PlatformConfig):
        super().__init__(config=config, platform=Platform("wechat_desktop"))
        desktop = _load_desktop_class()
        self.desktop = desktop()
        self.poll_seconds = max(
            1.0,
            float((config.extra or {}).get("poll_seconds") or os.getenv("WECHAT_DESKTOP_POLL_SECONDS", "2")),
        )
        self.allowed_chats = _allowed_chats(config)
        self._poll_task: asyncio.Task | None = None
        self._seen: dict[str, str] = {}
        self._recent_outbound: dict[str, str] = {}

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        del is_reconnect
        status = await asyncio.to_thread(self.desktop.status)
        if not status.get("available"):
            return False
        self._mark_connected()
        self._poll_task = asyncio.create_task(self._poll_loop())
        return True

    async def disconnect(self) -> None:
        self._running = False
        self._mark_disconnected()
        task = self._poll_task
        self._poll_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def _allowed(self, chat: str) -> bool:
        return not self.allowed_chats or chat in self.allowed_chats

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                unread = await asyncio.to_thread(self.desktop.unread_chats, 200)
                for row in unread:
                    chat = str(row.name or "").strip()
                    if not chat or not self._allowed(chat):
                        continue
                    messages = await asyncio.to_thread(self.desktop.get_messages, chat, 8)
                    if not messages:
                        continue
                    text = str(messages[-1].get("text") or "").strip()
                    if not text:
                        continue
                    fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()
                    if self._seen.get(chat) == fingerprint:
                        continue
                    if self._recent_outbound.get(chat) == fingerprint:
                        self._seen[chat] = fingerprint
                        continue
                    self._seen[chat] = fingerprint
                    source = self.build_source(
                        chat_id=chat,
                        chat_name=chat,
                        chat_type="dm",
                        user_id=chat,
                        user_name=chat,
                    )
                    event = MessageEvent(
                        text=text,
                        message_type=MessageType.TEXT,
                        source=source,
                        message_id=f"wechat-desktop-{fingerprint[:20]}",
                        raw_message={"chat": chat, "text": text, "transport": "windows-uia"},
                        timestamp=datetime.now(UTC),
                    )
                    await self.handle_message(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Desktop UI trees can temporarily disappear while WeChat is
                # minimized/restarting. Fail closed for this poll and retry.
                pass
            await asyncio.sleep(self.poll_seconds)

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SendResult:
        del reply_to, metadata
        chat = str(chat_id or "").strip()
        if not self._allowed(chat):
            return SendResult(success=False, error=f"WeChat chat is not allow-listed: {chat}")
        try:
            result = await asyncio.to_thread(self.desktop.send_message, chat, content)
        except Exception as exc:
            return SendResult(success=False, error=str(exc))
        if not result.get("sent") and not result.get("duplicate_suppressed"):
            return SendResult(success=False, error="WeChat desktop send did not complete")
        fingerprint = hashlib.sha256(str(content).strip().encode("utf-8")).hexdigest()
        self._recent_outbound[chat] = fingerprint
        return SendResult(success=True, message_id=f"wechat-desktop-{fingerprint[:20]}")

    async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
        chat = str(chat_id or "").strip()
        return {"name": chat, "type": "dm", "transport": "windows-uia"}


def register(ctx):
    ctx.register_platform(
        name="wechat_desktop",
        label="WeChat Desktop",
        adapter_factory=lambda cfg: WeChatDesktopPlatformAdapter(cfg),
        check_fn=check_requirements,
        validate_config=validate_config,
        env_enablement_fn=_env_enablement,
        cron_deliver_env_var="WECHAT_DESKTOP_HOME_CHAT",
        max_message_length=4000,
        platform_hint=(
            "You are replying through the user's locally logged-in Windows WeChat client. "
            "Use concise plain text. The connector verifies the exact conversation title before every send."
        ),
        emoji="💬",
    )
