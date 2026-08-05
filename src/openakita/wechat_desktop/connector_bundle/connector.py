from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests
import websockets
import yaml
from wxauto import WeChat

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.yaml"
LOG_PATH = ROOT / "connector.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
logger = logging.getLogger("openakita-wechat-connector")


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise RuntimeError("config.yaml 不存在，请先运行 pair.py 完成配对")
    data = yaml.safe_load(CONFIG_PATH.read_text("utf-8")) or {}
    for key in ("oa_url", "node_id", "node_token"):
        if not str(data.get(key) or "").strip():
            raise RuntimeError(f"config.yaml 缺少 {key}")
    return data


def ws_url(oa_url: str, node_id: str, token: str) -> str:
    base = oa_url.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[8:]
    elif base.startswith("http://"):
        base = "ws://" + base[7:]
    return f"{base}/api/wechat-desktop/ws?node_id={node_id}&token={token}&version=1.0.0"


class DesktopDriver:
    def __init__(self) -> None:
        self.wx = WeChat()
        self.active_account_id = os.environ.get("WECHAT_ACCOUNT_ID", "default")

    def accounts(self) -> list[dict[str, Any]]:
        nickname = getattr(self.wx, "nickname", "") or "当前微信"
        return [{"id": self.active_account_id, "nickname": nickname, "login_status": "logged_in"}]

    def conversations(self) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        sessions = self.wx.GetSessionList() or []
        groups: list[dict[str, str]] = []
        contacts: list[dict[str, str]] = []
        for item in sessions:
            name = str(item)
            row = {"id": name, "name": name}
            if name.endswith("群") or "群" in name:
                groups.append(row)
            else:
                contacts.append(row)
        return groups, contacts

    def listen(self, names: list[str]) -> None:
        for name in names:
            try:
                self.wx.AddListenChat(who=name, savepic=False)
            except Exception as exc:
                logger.warning("监听会话失败 %s: %s", name, exc)

    def poll_messages(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        messages = self.wx.GetListenMessage() or {}
        for chat, rows in messages.items():
            chat_name = str(getattr(chat, "who", None) or chat)
            for row in rows or []:
                sender = str(getattr(row, "sender", None) or getattr(row, "who", None) or "unknown")
                text = str(getattr(row, "content", None) or getattr(row, "text", None) or "").strip()
                if not text:
                    continue
                result.append(
                    {
                        "message_id": str(getattr(row, "id", None) or f"{chat_name}:{sender}:{time.time_ns()}"),
                        "wechat_account_id": self.active_account_id,
                        "chat_id": chat_name,
                        "chat_name": chat_name,
                        "chat_type": "group" if (chat_name.endswith("群") or "群" in chat_name) else "private",
                        "sender_id": sender,
                        "sender_name": sender,
                        "text": text,
                        "is_mentioned": bool(getattr(row, "is_at", False)),
                        "timestamp": time.time(),
                    }
                )
        return result

    def send_text(self, chat_id: str, text: str) -> None:
        self.wx.SendMsg(text, who=chat_id)


async def run() -> None:
    config = load_config()
    driver = DesktopDriver()
    url = ws_url(str(config["oa_url"]), str(config["node_id"]), str(config["node_token"]))
    current_bot_ids: list[str] = []
    allowed_chats: set[str] = set()

    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, max_size=8 * 1024 * 1024) as socket:
                logger.info("已连接 OpenAkita OA")
                accounts = driver.accounts()
                await socket.send(json.dumps({"event": "wechat.accounts.sync", "payload": {"accounts": accounts}}, ensure_ascii=False))
                groups, contacts = driver.conversations()
                await socket.send(
                    json.dumps(
                        {
                            "event": "wechat.conversations.sync",
                            "payload": {
                                "wechat_account_id": accounts[0]["id"],
                                "groups": groups,
                                "contacts": contacts,
                            },
                        },
                        ensure_ascii=False,
                    )
                )

                async def heartbeat() -> None:
                    while True:
                        await asyncio.sleep(20)
                        await socket.send(json.dumps({"event": "node.heartbeat", "payload": {}}))

                async def poll() -> None:
                    while True:
                        await asyncio.sleep(0.8)
                        for payload in driver.poll_messages():
                            for bot_id in current_bot_ids:
                                await socket.send(
                                    json.dumps(
                                        {"event": "wechat.message.received", "bot_id": bot_id, "payload": payload},
                                        ensure_ascii=False,
                                    )
                                )

                heartbeat_task = asyncio.create_task(heartbeat())
                poll_task = asyncio.create_task(poll())
                try:
                    async for raw in socket:
                        envelope = json.loads(raw)
                        event = envelope.get("event")
                        payload = envelope.get("payload") or {}
                        bot_id = str(envelope.get("bot_id") or "")
                        if event == "config.sync":
                            if bot_id and bot_id not in current_bot_ids:
                                current_bot_ids.append(bot_id)
                            allowed_chats = set(payload.get("allowed_groups") or []) | set(payload.get("allowed_contacts") or [])
                            driver.listen(sorted(allowed_chats))
                            await socket.send(json.dumps({"event": "config.applied", "bot_id": bot_id, "payload": {"ok": True}}))
                        elif event == "wechat.message.send":
                            request_id = str(envelope.get("request_id") or "")
                            await socket.send(json.dumps({"event": "wechat.message.accepted", "request_id": request_id, "bot_id": bot_id, "payload": {}}))
                            try:
                                driver.send_text(str(payload["chat_id"]), str(payload["text"]))
                                await socket.send(json.dumps({"event": "wechat.message.sent", "request_id": request_id, "bot_id": bot_id, "payload": {}}))
                            except Exception as exc:
                                await socket.send(
                                    json.dumps(
                                        {
                                            "event": "wechat.message.failed",
                                            "request_id": request_id,
                                            "bot_id": bot_id,
                                            "payload": {"detail": str(exc)},
                                        },
                                        ensure_ascii=False,
                                    )
                                )
                finally:
                    heartbeat_task.cancel()
                    poll_task.cancel()
        except Exception as exc:
            logger.exception("Connector 连接失败: %s", exc)
            await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        sys.exit(0)
