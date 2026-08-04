"""OpenAkita channel adapter for Windows WeChat desktop connectors."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ...wechat_desktop import wechat_desktop_manager
from ..base import ChannelAdapter, ChannelDeliveryUnavailable
from ..types import MediaFile, MessageContent, OutgoingMessage, UnifiedMessage


class WeChatDesktopAdapter(ChannelAdapter):
    """Routes messages through a paired Windows connector node.

    The Linux/VPS process never imports or executes wxauto. The connector owns all
    Windows UI automation and reports account, contact and delivery state to OA.
    """

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
        merge_window_seconds: int = 2,
        send_interval_seconds: int = 3,
        duplicate_ttl_seconds: int = 600,
        agent_timeout_seconds: int = 180,
        channel_name: str = "wechat_desktop",
        bot_id: str = "wechat-desktop",
        agent_profile_id: str = "default",
    ) -> None:
        super().__init__(
            channel_name=channel_name,
            bot_id=bot_id,
            agent_profile_id=agent_profile_id,
        )
        self.node_id = node_id.strip()
        self.wechat_account_id = wechat_account_id.strip()
        self.wechat_account_name = wechat_account_name.strip()
        self.allowed_groups = set(allowed_groups or [])
        self.allowed_contacts = set(allowed_contacts or [])
        self.ignore_senders = set(ignore_senders or [])
        self.mention_only = mention_only
        self.private_chat_enabled = private_chat_enabled
        self.auto_reply = auto_reply
        self.merge_window_seconds = max(0, int(merge_window_seconds))
        self.send_interval_seconds = max(0, int(send_interval_seconds))
        self.duplicate_ttl_seconds = max(1, int(duplicate_ttl_seconds))
        self.agent_timeout_seconds = max(1, int(agent_timeout_seconds))

    def collect_warnings(self) -> list[str]:
        warnings = super().collect_warnings()
        if not self.node_id:
            warnings.append(f"[{self.channel_name}] Windows 节点未选择")
        if not self.wechat_account_id:
            warnings.append(f"[{self.channel_name}] 微信账号未选择")
        if not self.allowed_groups and not self.allowed_contacts:
            warnings.append(f"[{self.channel_name}] 尚未配置允许回复的群聊或联系人")
        return warnings

    async def start(self) -> None:
        if not self.node_id:
            raise ValueError("wechat_desktop requires node_id")
        if not self.wechat_account_id:
            raise ValueError("wechat_desktop requires wechat_account_id")
        await wechat_desktop_manager.bind_account(
            self.node_id,
            self.wechat_account_id,
            self.bot_id,
            True,
        )
        await wechat_desktop_manager.register_bot_callback(self.bot_id, self._receive_payload)
        self._running = True
        await wechat_desktop_manager.send_command(
            self.node_id,
            {
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
                    "merge_window_seconds": self.merge_window_seconds,
                    "send_interval_seconds": self.send_interval_seconds,
                    "duplicate_ttl_seconds": self.duplicate_ttl_seconds,
                },
            },
        )

    async def stop(self) -> None:
        self._running = False
        await wechat_desktop_manager.unregister_bot_callback(self.bot_id)
        await wechat_desktop_manager.bind_account(
            self.node_id,
            self.wechat_account_id,
            self.bot_id,
            False,
        )

    async def _receive_payload(self, payload: dict[str, Any]) -> None:
        if not self._running or not self.auto_reply:
            return
        account_id = str(payload.get("wechat_account_id") or "")
        if account_id != self.wechat_account_id:
            return
        sender_id = str(payload.get("sender_id") or payload.get("sender_name") or "unknown")
        sender_name = str(payload.get("sender_name") or sender_id)
        if sender_id in self.ignore_senders or sender_name in self.ignore_senders:
            return
        chat_id = str(payload.get("chat_id") or "")
        chat_type = str(payload.get("chat_type") or "private")
        if not chat_id:
            return
        if chat_type == "group":
            if chat_id not in self.allowed_groups:
                return
            if self.mention_only and not bool(payload.get("is_mentioned")):
                return
        elif not self.private_chat_enabled or chat_id not in self.allowed_contacts:
            return
        text = str(payload.get("text") or "").strip()
        if not text:
            return
        channel_message_id = str(payload.get("message_id") or payload.get("request_id") or "")
        if not channel_message_id:
            return
        timestamp_value = payload.get("timestamp")
        timestamp = datetime.fromtimestamp(float(timestamp_value)) if timestamp_value else datetime.now()
        message = UnifiedMessage.create(
            channel=self.channel_name,
            channel_message_id=channel_message_id,
            user_id=f"wechat-desktop:{self.node_id}:{sender_id}",
            channel_user_id=sender_id,
            chat_id=chat_id,
            content=MessageContent.text_only(text),
            bot_instance_id=self.bot_instance_id,
            chat_type=chat_type,
            timestamp=timestamp,
            is_mentioned=bool(payload.get("is_mentioned")),
            is_direct_message=chat_type == "private",
            raw=payload,
            metadata={
                "node_id": self.node_id,
                "wechat_account_id": self.wechat_account_id,
                "wechat_account_name": self.wechat_account_name,
                "sender_name": sender_name,
                "chat_name": payload.get("chat_name"),
            },
        )
        await self._emit_message(message)

    async def send_message(self, message: OutgoingMessage) -> str:
        if not self._running:
            raise ChannelDeliveryUnavailable(
                "微信（桌面版）Bot 未运行",
                channel=self.channel_name,
                chat_id=message.chat_id,
                reason="bot_not_running",
            )
        text = message.content.text if message.content else ""
        if not text:
            raise ValueError("wechat_desktop currently supports text messages only")
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
        return request_id

    async def download_media(self, media: MediaFile) -> Path:
        if media.local_path:
            return Path(media.local_path)
        raise NotImplementedError("wechat_desktop media download is not implemented")

    async def upload_media(self, path: Path, mime_type: str) -> MediaFile:
        media = MediaFile.create(path.name, mime_type, size=path.stat().st_size)
        media.local_path = str(path)
        return media
