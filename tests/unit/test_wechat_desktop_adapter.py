from __future__ import annotations

import asyncio
from typing import Any

import pytest

import openakita.channels.adapters.wechat_desktop as module
from openakita.channels.adapters.wechat_desktop import WeChatDesktopAdapter
from openakita.channels.types import OutgoingMessage


class FakeManager:
    def __init__(self) -> None:
        self.callback = None
        self.commands: list[dict[str, Any]] = []

    async def bind_account(self, *_args, **_kwargs) -> None:
        return None

    async def register_bot_callback(self, _bot_id, callback) -> None:
        self.callback = callback

    async def unregister_bot_callback(self, _bot_id) -> None:
        self.callback = None

    async def send_command(self, _node_id, command) -> None:
        self.commands.append(command)


@pytest.mark.asyncio
async def test_allowlist_merge_and_duplicate_filter(monkeypatch) -> None:
    manager = FakeManager()
    monkeypatch.setattr(module, "wechat_desktop_manager", manager)
    adapter = WeChatDesktopAdapter(
        node_id="node-a",
        wechat_account_id="account-a",
        allowed_groups=["group-a"],
        merge_window_seconds=0,
        send_interval_seconds=0,
        bot_id="bot-a",
    )
    received = []

    async def on_message(message) -> None:
        received.append(message)

    adapter.on_message(on_message)
    await adapter.start()
    payload = {
        "wechat_account_id": "account-a",
        "message_id": "m1",
        "chat_id": "group-a",
        "chat_type": "group",
        "sender_id": "u1",
        "sender_name": "客户",
        "text": "你好",
        "timestamp": 1,
    }
    await manager.callback(payload)
    await manager.callback(payload)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(received) == 1
    assert received[0].text == "你好"
    assert received[0].metadata["merge_count"] == 1

    await adapter.send_message(OutgoingMessage.text("group-a", "已收到"))
    assert manager.commands[-1]["event"] == "wechat.message.send"
    await adapter.stop()


@pytest.mark.asyncio
async def test_human_takeover_suppresses_agent(monkeypatch) -> None:
    manager = FakeManager()
    monkeypatch.setattr(module, "wechat_desktop_manager", manager)
    adapter = WeChatDesktopAdapter(
        node_id="node-a",
        wechat_account_id="account-a",
        allowed_groups=["group-a"],
        human_takeover=True,
        merge_window_seconds=0,
        bot_id="bot-a",
    )
    received = []

    async def on_message(message) -> None:
        received.append(message)

    adapter.on_message(on_message)
    await adapter.start()
    await manager.callback(
        {
            "wechat_account_id": "account-a",
            "message_id": "m1",
            "chat_id": "group-a",
            "chat_type": "group",
            "sender_id": "u1",
            "text": "人工正在处理",
        }
    )
    await asyncio.sleep(0)
    assert received == []
    await adapter.stop()
