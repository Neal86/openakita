"""OpenAkita channel adapter for Windows WeChat desktop connectors."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ...wechat_desktop import wechat_desktop_manager
from ..base import ChannelAdapter, ChannelDeliveryUnavailable
from ..types import MediaFile, MessageContent, OutgoingMessage, UnifiedMessage


class WeChatDesktopAdapter(ChannelAdapter):
    """Routes one Windows-node WeChat account to one OpenAkita Agent."""

    capabilities = {
        **ChannelAdapter.capabilities,
        "streaming": False,
        "send_image": False,
        "send_file": False,
        "get_chat_info": True,
        "get_user_info": True,
        "get_recent_messages": False,
        "markdown": False,
    }

    def __init__(
        self,
        *,
        node_id: str,
        wechat_account_id: str,
        wechat_account_name: str = "",
        allowed_groups: list[str] | None = None,
        allowed_contacts: list[str] | None = None,
        ignore_senders: list[str] | None = None,
        mention_only: bool = False,
        private_chat_enabled: bool = False,
        auto_reply: bool = True,
        human_takeover: bool = False,
        merge_window_seconds: int = 2,
        send_interval_seconds: int = 3,
        duplicate_ttl_seconds: int = 600,
        agent_timeout_seconds: int = 180,
        channel_name: str = "wechat_desktop",
        bot_id: str = "wechat-desktop",
        agent_profile_id: str = "default",
    ) -> None:
        super().__init__(channel_name=channel_name, bot_id=bot_id, agent_profile_id=agent_profile_id)
        self.node_id = node_id.strip()
        self.wechat_account_id = wechat_account_id.strip()
        self.wechat_account_name = wechat_account_name.strip()
        self.allowed_groups = set(allowed_groups or [])
        self.allowed_contacts = set(allowed_contacts or [])
        self.ignore_senders = set(ignore_senders or [])
        self.mention_only = mention_only
        self.private_chat_enabled = private_chat_enabled
        self.auto_reply = auto_reply
        self.human_takeover = human_takeover
        self.merge_window_seconds = max(0, int(merge_window_seconds))
        self.send_interval_seconds = max(0, int(send_interval_seconds))
        self.duplicate_ttl_seconds = max(1, int(duplicate_ttl_seconds))
        self.agent_timeout_seconds = max(1, int(agent_timeout_seconds))
        self._seen: dict[str, float] = {}
        self._pending: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._merge_tasks: dict[tuple[str, str], asyncio.Task[None]] = {}
        self._last_send: dict[str, float] = {}
        self._send_locks: dict[str, asyncio.Lock] = {}

    def collect_warnings(self) -> list[str]:
        warnings = super().collect_warnings()
        if not self.node_id:
            warnings.append(f"[{self.channel_name}] Windows 节点未选择")
        if not self.wechat_account_id:
            warnings.append(f"[{self.channel_name}] 微信账号未选择")
        if not self.allowed_groups and not self.allowed_contacts:
            warnings.append(f"[{self.channel_name}] 尚未配置允许回复的群聊或联系人")
        if self.human_takeover:
            warnings.append(f"[{self.channel_name}] 当前处于人工接管状态，自动回复已暂停")
        return warnings

    def _config_command(self) -> dict[str, Any]:
        return {
            "version": 1,
            "event": "config.sync",
            "bot_id": self.bot_id,
            "payload": {
                "wechat_account_id": self.wechat_account_id,
                "allowed_groups": sorted(self.allowed_groups),
                "allowed_contacts": sorted(self.allowed_contacts),
                "ignore_senders": sorted(self.ignore_senders),
                "mention_only": self.mention_only,
                "private_chat_enabled": self.private_chat_enabled,
                "auto_reply": self.auto_reply,
                "human_takeover": self.human_takeover,
                "merge_window_seconds": self.merge_window_seconds,
                "send_interval_seconds": self.send_interval_seconds,
                "duplicate_ttl_seconds": self.duplicate_ttl_seconds,
            },
        }

    async def start(self) -> None:
        if not self.node_id:
            raise ValueError("wechat_desktop requires node_id")
        if not self.wechat_account_id:
            raise ValueError("wechat_desktop requires wechat_account_id")
        await wechat_desktop_manager.bind_account(self.node_id, self.wechat_account_id, self.bot_id, True)
        await wechat_desktop_manager.register_bot_callback(self.bot_id, self._receive_payload)
        self._running = True
        try:
            await wechat_desktop_manager.send_command(self.node_id, self._config_command())
        except ConnectionError:
            # OA may start before the Windows connector. The bot remains configured;
            # the UI shows the node offline and delivery fails explicitly until reconnect.
            pass

    async def stop(self) -> None:
        self._running = False
        for task in self._merge_tasks.values():
            task.cancel()
        self._merge_tasks.clear()
        self._pending.clear()
        await wechat_desktop_manager.unregister_bot_callback(self.bot_id)
        await wechat_desktop_manager.bind_account(self.node_id, self.wechat_account_id, self.bot_id, False)

    def _accept_payload(self, payload: dict[str, Any]) -> tuple[str, str, str] | None:
        if not self._running or not self.auto_reply or self.human_takeover:
            return None
        if str(payload.get("wechat_account_id") or "") != self.wechat_account_id:
            return None
        sender_id = str(payload.get("sender_id") or payload.get("sender_name") or "unknown")
        sender_name = str(payload.get("sender_name") or sender_id)
        if sender_id in self.ignore_senders or sender_name in self.ignore_senders:
            return None
        chat_id = str(payload.get("chat_id") or "")
        chat_type = str(payload.get("chat_type") or "private")
        if not chat_id:
            return None
        if chat_type == "group":
            if chat_id not in self.allowed_groups:
                return None
            if self.mention_only and not bool(payload.get("is_mentioned")):
                return None
        elif not self.private_chat_enabled or chat_id not in self.allowed_contacts:
            return None
        if not str(payload.get("text") or "").strip():
            return None
        message_id = str(payload.get("message_id") or payload.get("request_id") or "")
        if not message_id:
            return None
        now = time.monotonic()
        self._seen = {key: ts for key, ts in self._seen.items() if now - ts < self.duplicate_ttl_seconds}
        if message_id in self._seen:
            return None
        self._seen[message_id] = now
        return chat_id, chat_type, sender_id

    async def _receive_payload(self, payload: dict[str, Any]) -> None:
        accepted = self._accept_payload(payload)
        if accepted is None:
            return
        chat_id, _chat_type, sender_id = accepted
        key = (chat_id, sender_id)
        self._pending.setdefault(key, []).append(dict(payload))
        old_task = self._merge_tasks.pop(key, None)
        if old_task:
            old_task.cancel()
        self._merge_tasks[key] = asyncio.create_task(self._flush_after_window(key))

    async def _flush_after_window(self, key: tuple[str, str]) -> None:
        try:
            if self.merge_window_seconds:
                await asyncio.sleep(self.merge_window_seconds)
            rows = self._pending.pop(key, [])
            if not rows or not self._running:
                return
            first, last = rows[0], rows[-1]
            chat_id, sender_id = key
            sender_name = str(last.get("sender_name") or sender_id)
            text = "\n".join(str(row.get("text") or "").strip() for row in rows if str(row.get("text") or "").strip())
            ids = [str(row.get("message_id") or row.get("request_id") or "") for row in rows]
            timestamp_value = last.get("timestamp")
            timestamp = datetime.fromtimestamp(float(timestamp_value)) if timestamp_value else datetime.now()
            chat_type = str(last.get("chat_type") or "private")
            message = UnifiedMessage.create(
                channel=self.channel_name,
                channel_message_id=ids[-1],
                user_id=f"wechat-desktop:{self.node_id}:{sender_id}",
                channel_user_id=sender_id,
                chat_id=chat_id,
                content=MessageContent.text_only(text),
                bot_instance_id=self.bot_instance_id,
                chat_type=chat_type,
                timestamp=timestamp,
                is_mentioned=any(bool(row.get("is_mentioned")) for row in rows),
                is_direct_message=chat_type == "private",
                raw={"messages": rows},
                metadata={
                    "node_id": self.node_id,
                    "wechat_account_id": self.wechat_account_id,
                    "wechat_account_name": self.wechat_account_name,
                    "sender_name": sender_name,
                    "chat_name": last.get("chat_name"),
                    "merged_message_ids": ids,
                    "merge_count": len(rows),
                },
            )
            await self._emit_message(message)
        except asyncio.CancelledError:
            return
        finally:
            self._merge_tasks.pop(key, None)

    async def send_message(self, message: OutgoingMessage) -> str:
        if not self._running:
            raise ChannelDeliveryUnavailable("微信（桌面版）Bot 未运行", channel=self.channel_name, chat_id=message.chat_id, reason="bot_not_running")
        text = message.content.text if message.content else ""
        if not text:
            raise ValueError("wechat_desktop currently supports text messages only")
        lock = self._send_locks.setdefault(message.chat_id, asyncio.Lock())
        async with lock:
            elapsed = time.monotonic() - self._last_send.get(message.chat_id, 0.0)
            if elapsed < self.send_interval_seconds:
                await asyncio.sleep(self.send_interval_seconds - elapsed)
            request_id = f"wechat-send-{self.bot_id}-{uuid.uuid4().hex[:12]}"
            try:
                await wechat_desktop_manager.send_command(
                    self.node_id,
                    {
                        "version": 1,
                        "event": "wechat.message.send",
                        "request_id": request_id,
                        "bot_id": self.bot_id,
                        "payload": {
                            "wechat_account_id": self.wechat_account_id,
                            "chat_id": message.chat_id,
                            "text": text,
                            "reply_to": message.reply_to,
                        },
                    },
                )
            except ConnectionError as exc:
                raise ChannelDeliveryUnavailable(
                    "Windows 微信节点离线，无法发送消息",
                    channel=self.channel_name,
                    chat_id=message.chat_id,
                    reason="node_offline",
                    retryable=True,
                ) from exc
            self._last_send[message.chat_id] = time.monotonic()
            return request_id

    async def download_media(self, media: MediaFile) -> Path:
        if media.local_path:
            return Path(media.local_path)
        raise NotImplementedError("wechat_desktop media download is not implemented")

    async def upload_media(self, path: Path, mime_type: str) -> MediaFile:
        media = MediaFile.create(path.name, mime_type, size=path.stat().st_size)
        media.local_path = str(path)
        return media
