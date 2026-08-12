from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any, Callable, TypeVar

import websockets
import yaml
from wxauto4 import WeChat

from openakita.windows_connector.executor import WindowsCommandExecutor

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.yaml"
LOG_PATH = ROOT / "connector.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
logger = logging.getLogger("openakita-wechat-connector")
T = TypeVar("T")


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
        self._messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self._listening: set[str] = set()

    def accounts(self) -> list[dict[str, Any]]:
        nickname = "当前微信"
        try:
            info = self.wx.ChatInfo() or {}
            nickname = str(info.get("account") or info.get("nickname") or nickname)
        except Exception:
            pass
        return [{"id": self.active_account_id, "nickname": nickname, "login_status": "logged_in"}]

    def conversations(self) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        groups: list[dict[str, str]] = []
        contacts: list[dict[str, str]] = []
        try:
            sessions = self.wx.GetSessionList() or []
        except Exception:
            sessions = []
        for item in sessions:
            name = str(getattr(item, "name", None) or getattr(item, "who", None) or item)
            if not name:
                continue
            row = {"id": name, "name": name}
            if name.endswith("群") or "群" in name:
                groups.append(row)
            else:
                contacts.append(row)
        return groups, contacts

    def _on_message(self, msg: Any, chat: Any) -> None:
        try:
            chat_name = str(getattr(chat, "who", None) or getattr(chat, "name", None) or chat)
            sender = str(getattr(msg, "sender", None) or getattr(msg, "who", None) or "unknown")
            text = str(getattr(msg, "content", None) or getattr(msg, "text", None) or "").strip()
            if not text:
                return
            self._messages.put(
                {
                    "message_id": str(getattr(msg, "id", None) or f"{chat_name}:{sender}:{time.time_ns()}"),
                    "wechat_account_id": self.active_account_id,
                    "chat_id": chat_name,
                    "chat_name": chat_name,
                    "chat_type": "group" if (chat_name.endswith("群") or "群" in chat_name) else "private",
                    "sender_id": sender,
                    "sender_name": sender,
                    "text": text,
                    "is_mentioned": bool(getattr(msg, "is_at", False)),
                    "timestamp": time.time(),
                }
            )
        except Exception:
            logger.exception("处理微信消息回调失败")

    def listen(self, names: list[str]) -> None:
        for name in names:
            if name in self._listening:
                continue
            try:
                self.wx.AddListenChat(who=name, callback=self._on_message)
                self._listening.add(name)
                logger.info("开始监听微信会话: %s", name)
            except Exception as exc:
                logger.warning("监听会话失败 %s: %s", name, exc)
        try:
            self.wx.StartListening()
        except Exception:
            pass

    def poll_messages(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        while True:
            try:
                rows.append(self._messages.get_nowait())
            except queue.Empty:
                break
        return rows

    def send_text(self, chat_id: str, text: str) -> None:
        self.wx.SendMsg(text, who=chat_id)

    def close(self) -> None:
        try:
            self.wx.StopListening()
        except Exception:
            pass


async def _run_in_pool(
    pool: ThreadPoolExecutor,
    func: Callable[..., T],
    *args: Any,
) -> T:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(pool, partial(func, *args))


async def _cancel_tasks(*tasks: asyncio.Task[Any]) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def run() -> None:
    config = load_config()
    driver_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="openakita-wechat")
    computer_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="openakita-windows")
    driver: DesktopDriver | None = None
    try:
        driver = await _run_in_pool(driver_pool, DesktopDriver)
        computer = WindowsCommandExecutor()
        url = ws_url(str(config["oa_url"]), str(config["node_id"]), str(config["node_token"]))
        bot_configs: dict[str, dict[str, Any]] = {}

        async def driver_call(func: Callable[..., T], *args: Any) -> T:
            return await _run_in_pool(driver_pool, func, *args)

        async def computer_resources() -> list[dict[str, Any]]:
            return await _run_in_pool(computer_pool, computer.resources)

        async def computer_execute(payload: dict[str, Any]) -> dict[str, Any]:
            return await _run_in_pool(
                computer_pool,
                lambda: asyncio.run(computer.execute(payload)),
            )

        while True:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=8 * 1024 * 1024,
                ) as socket:
                    logger.info("已连接 OpenAkita OA")
                    accounts = await driver_call(driver.accounts)
                    await socket.send(json.dumps({"event": "wechat.accounts.sync", "payload": {"accounts": accounts}}, ensure_ascii=False))
                    groups, contacts = await driver_call(driver.conversations)
                    await socket.send(json.dumps({"event": "wechat.conversations.sync", "payload": {"wechat_account_id": accounts[0]["id"], "groups": groups, "contacts": contacts}}, ensure_ascii=False))
                    await socket.send(json.dumps({"event": "windows.resources.sync", "payload": {"resources": await computer_resources()}}, ensure_ascii=False))

                    async def heartbeat() -> None:
                        while True:
                            await asyncio.sleep(20)
                            await socket.send(json.dumps({"event": "node.heartbeat", "payload": {}}))

                    async def resource_poll() -> None:
                        previous = ""
                        while True:
                            await asyncio.sleep(8)
                            resources = await computer_resources()
                            signature = json.dumps(resources, ensure_ascii=False, sort_keys=True)
                            if signature != previous:
                                previous = signature
                                await socket.send(json.dumps({"event": "windows.resources.sync", "payload": {"resources": resources}}, ensure_ascii=False))

                    async def poll() -> None:
                        while True:
                            await asyncio.sleep(0.5)
                            for message_payload in driver.poll_messages():
                                for bot_id, cfg in list(bot_configs.items()):
                                    if str(cfg.get("wechat_account_id") or "") != message_payload["wechat_account_id"]:
                                        continue
                                    await socket.send(json.dumps({"event": "wechat.message.received", "bot_id": bot_id, "payload": message_payload}, ensure_ascii=False))

                    heartbeat_task = asyncio.create_task(heartbeat())
                    resource_task = asyncio.create_task(resource_poll())
                    poll_task = asyncio.create_task(poll())
                    try:
                        async for raw in socket:
                            envelope = json.loads(raw)
                            event = envelope.get("event")
                            payload = envelope.get("payload") or {}
                            bot_id = str(envelope.get("bot_id") or "")
                            if event == "windows.permissions.sync":
                                computer.sync_grants(payload.get("grants") or [])
                            elif event == "windows.resources.refresh":
                                await socket.send(json.dumps({"event": "windows.resources.sync", "payload": {"resources": await computer_resources()}}, ensure_ascii=False))
                            elif event == "windows.command":
                                request_id = str(envelope.get("request_id") or "")
                                try:
                                    result = await computer_execute(dict(payload))
                                except Exception as exc:
                                    result = {"ok": False, "error": str(exc), "error_type": type(exc).__name__}
                                await socket.send(json.dumps({"event": "windows.command.result", "request_id": request_id, "payload": result}, ensure_ascii=False))
                            elif event == "config.sync":
                                bot_configs[bot_id] = dict(payload)
                                chats = set(payload.get("allowed_groups") or []) | set(payload.get("allowed_contacts") or [])
                                await driver_call(driver.listen, sorted(chats))
                                await socket.send(json.dumps({"event": "config.applied", "bot_id": bot_id, "payload": {"ok": True}}))
                            elif event == "wechat.message.send":
                                request_id = str(envelope.get("request_id") or "")
                                await socket.send(json.dumps({"event": "wechat.message.accepted", "request_id": request_id, "bot_id": bot_id, "payload": {}}))
                                try:
                                    await driver_call(driver.send_text, str(payload["chat_id"]), str(payload["text"]))
                                    await socket.send(json.dumps({"event": "wechat.message.sent", "request_id": request_id, "bot_id": bot_id, "payload": {}}))
                                except Exception as exc:
                                    await socket.send(json.dumps({"event": "wechat.message.failed", "request_id": request_id, "bot_id": bot_id, "payload": {"detail": str(exc)}}, ensure_ascii=False))
                    finally:
                        await _cancel_tasks(heartbeat_task, resource_task, poll_task)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Connector 连接失败: %s", exc)
                await asyncio.sleep(5)
    finally:
        if driver is not None:
            try:
                await _run_in_pool(driver_pool, driver.close)
            except Exception:
                logger.exception("关闭微信监听失败")
        driver_pool.shutdown(wait=True, cancel_futures=True)
        computer_pool.shutdown(wait=True, cancel_futures=True)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        sys.exit(0)
