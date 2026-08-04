"""Runtime registry for Windows WeChat connector nodes.

The manager is intentionally transport-agnostic. A WebSocket endpoint or an in-process
Windows connector registers a node session here, while channel adapters use the same
API to send commands and receive inbound events.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable

SendCallable = Callable[[dict[str, Any]], Awaitable[None]]
InboundCallback = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(slots=True)
class WeChatAccount:
    id: str
    nickname: str
    avatar_url: str = ""
    login_status: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WeChatNode:
    id: str
    name: str
    status: str = "offline"
    connector_version: str = ""
    last_heartbeat_at: datetime | None = None
    accounts: dict[str, WeChatAccount] = field(default_factory=dict)
    send: SendCallable | None = None


@dataclass(slots=True)
class PairingTicket:
    code_hash: str
    expires_at: datetime
    node_name: str
    used: bool = False


class WeChatDesktopManager:
    """Owns connector sessions, pairings, account bindings and message routing."""

    def __init__(self) -> None:
        self._nodes: dict[str, WeChatNode] = {}
        self._pairings: dict[str, PairingTicket] = {}
        self._bindings: dict[tuple[str, str], str] = {}
        self._callbacks: dict[str, InboundCallback] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    async def create_pairing_code(self, node_name: str, ttl_seconds: int = 600) -> str:
        code = "".join(str(secrets.randbelow(10)) for _ in range(8))
        async with self._lock:
            self._pairings[self._hash(code)] = PairingTicket(
                code_hash=self._hash(code),
                expires_at=datetime.now(UTC) + timedelta(seconds=max(60, ttl_seconds)),
                node_name=node_name.strip() or "Windows WeChat Connector",
            )
        return code

    async def consume_pairing_code(self, code: str) -> tuple[str, str, str]:
        """Consume a one-time code and return ``(node_id, node_token, node_name)``."""
        digest = self._hash(code.strip())
        async with self._lock:
            ticket = self._pairings.get(digest)
            if ticket is None or ticket.used or ticket.expires_at < datetime.now(UTC):
                raise ValueError("invalid or expired pairing code")
            ticket.used = True
            node_id = f"wechat-node-{secrets.token_hex(5)}"
            node_token = secrets.token_urlsafe(32)
            self._nodes[node_id] = WeChatNode(id=node_id, name=ticket.node_name)
            return node_id, node_token, ticket.node_name

    async def attach_node(
        self,
        node_id: str,
        *,
        send: SendCallable,
        connector_version: str = "",
    ) -> WeChatNode:
        async with self._lock:
            node = self._nodes.setdefault(node_id, WeChatNode(id=node_id, name=node_id))
            node.send = send
            node.status = "online"
            node.connector_version = connector_version
            node.last_heartbeat_at = datetime.now(UTC)
            return node

    async def detach_node(self, node_id: str) -> None:
        async with self._lock:
            node = self._nodes.get(node_id)
            if node:
                node.status = "offline"
                node.send = None
                node.last_heartbeat_at = datetime.now(UTC)

    async def heartbeat(self, node_id: str) -> None:
        async with self._lock:
            node = self._nodes.get(node_id)
            if node:
                node.status = "online"
                node.last_heartbeat_at = datetime.now(UTC)

    async def sync_accounts(self, node_id: str, accounts: list[dict[str, Any]]) -> None:
        async with self._lock:
            node = self._nodes.setdefault(node_id, WeChatNode(id=node_id, name=node_id))
            node.accounts = {
                str(item["id"]): WeChatAccount(
                    id=str(item["id"]),
                    nickname=str(item.get("nickname") or item["id"]),
                    avatar_url=str(item.get("avatar_url") or ""),
                    login_status=str(item.get("login_status") or "unknown"),
                    raw=dict(item),
                )
                for item in accounts
                if item.get("id")
            }

    async def list_nodes(self) -> list[dict[str, Any]]:
        async with self._lock:
            return [
                {
                    "id": node.id,
                    "name": node.name,
                    "status": node.status,
                    "connector_version": node.connector_version,
                    "last_heartbeat_at": node.last_heartbeat_at.isoformat()
                    if node.last_heartbeat_at
                    else None,
                    "accounts": [
                        {
                            "id": account.id,
                            "nickname": account.nickname,
                            "avatar_url": account.avatar_url,
                            "login_status": account.login_status,
                        }
                        for account in node.accounts.values()
                    ],
                }
                for node in self._nodes.values()
            ]

    async def bind_account(self, node_id: str, account_id: str, bot_id: str, enabled: bool) -> None:
        """Enforce one enabled bot per WeChat account."""
        key = (node_id, account_id)
        async with self._lock:
            existing = self._bindings.get(key)
            if enabled and existing and existing != bot_id:
                raise ValueError(
                    f"WeChat account {account_id} on node {node_id} is already bound to bot {existing}"
                )
            if enabled:
                self._bindings[key] = bot_id
            elif existing == bot_id:
                self._bindings.pop(key, None)

    async def register_bot_callback(self, bot_id: str, callback: InboundCallback) -> None:
        async with self._lock:
            self._callbacks[bot_id] = callback

    async def unregister_bot_callback(self, bot_id: str) -> None:
        async with self._lock:
            self._callbacks.pop(bot_id, None)

    async def dispatch_inbound(self, bot_id: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            callback = self._callbacks.get(bot_id)
        if callback is None:
            raise ValueError(f"wechat desktop bot is not running: {bot_id}")
        await callback(payload)

    async def send_command(self, node_id: str, command: dict[str, Any]) -> None:
        async with self._lock:
            node = self._nodes.get(node_id)
            send = node.send if node and node.status == "online" else None
        if send is None:
            raise ConnectionError(f"wechat desktop node is offline: {node_id}")
        await send(command)


wechat_desktop_manager = WeChatDesktopManager()
