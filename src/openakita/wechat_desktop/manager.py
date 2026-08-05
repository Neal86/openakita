"""Persistent runtime registry for Windows WeChat connector nodes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable

SendCallable = Callable[[dict[str, Any]], Awaitable[None]]
InboundCallback = Callable[[dict[str, Any]], Awaitable[None]]
STATE_PATH = Path("data/wechat_desktop/nodes.json")


@dataclass(slots=True)
class WeChatConversation:
    id: str
    name: str
    type: str


@dataclass(slots=True)
class WeChatAccount:
    id: str
    nickname: str
    avatar_url: str = ""
    login_status: str = "unknown"
    groups: dict[str, WeChatConversation] = field(default_factory=dict)
    contacts: dict[str, WeChatConversation] = field(default_factory=dict)


@dataclass(slots=True)
class WeChatNode:
    id: str
    name: str
    token_hash: str
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


@dataclass(slots=True)
class DeliveryReceipt:
    request_id: str
    bot_id: str
    node_id: str
    status: str
    detail: str = ""
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class WeChatDesktopManager:
    def __init__(self, state_path: Path = STATE_PATH) -> None:
        self._state_path = state_path
        self._nodes: dict[str, WeChatNode] = {}
        self._pairings: dict[str, PairingTicket] = {}
        self._bindings: dict[tuple[str, str], str] = {}
        self._callbacks: dict[str, InboundCallback] = {}
        self._receipts: dict[str, DeliveryReceipt] = {}
        self._lock = asyncio.Lock()
        self._load_state()

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _load_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text("utf-8"))
            for raw in data.get("nodes", []):
                accounts: dict[str, WeChatAccount] = {}
                for item in raw.get("accounts", []):
                    groups = {g["id"]: WeChatConversation(g["id"], g.get("name", g["id"]), "group") for g in item.get("groups", []) if g.get("id")}
                    contacts = {c["id"]: WeChatConversation(c["id"], c.get("name", c["id"]), "private") for c in item.get("contacts", []) if c.get("id")}
                    account = WeChatAccount(
                        id=str(item["id"]), nickname=str(item.get("nickname") or item["id"]),
                        avatar_url=str(item.get("avatar_url") or ""),
                        login_status="offline", groups=groups, contacts=contacts,
                    )
                    accounts[account.id] = account
                node = WeChatNode(
                    id=str(raw["id"]), name=str(raw.get("name") or raw["id"]),
                    token_hash=str(raw.get("token_hash") or ""), status="offline",
                    connector_version=str(raw.get("connector_version") or ""), accounts=accounts,
                )
                self._nodes[node.id] = node
            for item in data.get("bindings", []):
                self._bindings[(str(item["node_id"]), str(item["account_id"]))] = str(item["bot_id"])
        except Exception:
            self._nodes = {}
            self._bindings = {}

    def _save_state_locked(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "nodes": [
                {
                    "id": node.id, "name": node.name, "token_hash": node.token_hash,
                    "connector_version": node.connector_version,
                    "accounts": [
                        {
                            "id": account.id, "nickname": account.nickname,
                            "avatar_url": account.avatar_url,
                            "groups": [{"id": x.id, "name": x.name} for x in account.groups.values()],
                            "contacts": [{"id": x.id, "name": x.name} for x in account.contacts.values()],
                        }
                        for account in node.accounts.values()
                    ],
                }
                for node in self._nodes.values()
            ],
            "bindings": [
                {"node_id": node_id, "account_id": account_id, "bot_id": bot_id}
                for (node_id, account_id), bot_id in self._bindings.items()
            ],
        }
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(self._state_path)

    async def create_pairing_code(self, node_name: str, ttl_seconds: int = 600) -> str:
        code = "".join(str(secrets.randbelow(10)) for _ in range(8))
        async with self._lock:
            self._pairings[self._hash(code)] = PairingTicket(
                code_hash=self._hash(code), expires_at=datetime.now(UTC) + timedelta(seconds=max(60, ttl_seconds)),
                node_name=node_name.strip() or "Windows WeChat Connector",
            )
        return code

    async def consume_pairing_code(self, code: str) -> tuple[str, str, str]:
        digest = self._hash(code.strip())
        async with self._lock:
            ticket = self._pairings.get(digest)
            if ticket is None or ticket.used or ticket.expires_at < datetime.now(UTC):
                raise ValueError("invalid or expired pairing code")
            ticket.used = True
            node_id = f"wechat-node-{secrets.token_hex(5)}"
            node_token = secrets.token_urlsafe(32)
            self._nodes[node_id] = WeChatNode(node_id, ticket.node_name, self._hash(node_token))
            self._save_state_locked()
            return node_id, node_token, ticket.node_name

    async def authenticate_node(self, node_id: str, node_token: str) -> bool:
        async with self._lock:
            node = self._nodes.get(node_id)
            expected = node.token_hash if node else ""
        return bool(expected) and secrets.compare_digest(expected, self._hash(node_token))

    async def revoke_node(self, node_id: str) -> bool:
        async with self._lock:
            if self._nodes.pop(node_id, None) is None:
                return False
            for key in [key for key in self._bindings if key[0] == node_id]:
                self._bindings.pop(key, None)
            self._save_state_locked()
            return True

    async def attach_node(self, node_id: str, *, node_token: str, send: SendCallable, connector_version: str = "") -> WeChatNode:
        if not await self.authenticate_node(node_id, node_token):
            raise PermissionError("invalid connector credentials")
        async with self._lock:
            node = self._nodes[node_id]
            node.send = send
            node.status = "online"
            node.connector_version = connector_version
            node.last_heartbeat_at = datetime.now(UTC)
            self._save_state_locked()
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
            node = self._nodes.get(node_id)
            if node is None:
                raise ValueError("unknown connector node")
            previous = node.accounts
            synced: dict[str, WeChatAccount] = {}
            for item in accounts:
                account_id = str(item.get("id") or "").strip()
                if not account_id:
                    continue
                old = previous.get(account_id)
                synced[account_id] = WeChatAccount(
                    id=account_id, nickname=str(item.get("nickname") or account_id),
                    avatar_url=str(item.get("avatar_url") or ""),
                    login_status=str(item.get("login_status") or "unknown"),
                    groups=old.groups if old else {}, contacts=old.contacts if old else {},
                )
            node.accounts = synced
            self._save_state_locked()

    async def sync_conversations(self, node_id: str, account_id: str, *, groups: list[dict[str, Any]], contacts: list[dict[str, Any]]) -> None:
        async with self._lock:
            node = self._nodes.get(node_id)
            account = node.accounts.get(account_id) if node else None
            if account is None:
                raise ValueError("unknown WeChat account")
            account.groups = self._conversation_map(groups, "group")
            account.contacts = self._conversation_map(contacts, "private")
            self._save_state_locked()

    @staticmethod
    def _conversation_map(items: list[dict[str, Any]], kind: str) -> dict[str, WeChatConversation]:
        return {
            str(item["id"]): WeChatConversation(str(item["id"]), str(item.get("name") or item.get("nickname") or item["id"]), kind)
            for item in items if item.get("id")
        }

    async def list_nodes(self) -> list[dict[str, Any]]:
        async with self._lock:
            return [self._node_dict(node) for node in self._nodes.values()]

    async def get_node(self, node_id: str) -> dict[str, Any] | None:
        async with self._lock:
            node = self._nodes.get(node_id)
            return self._node_dict(node) if node else None

    @staticmethod
    def _node_dict(node: WeChatNode) -> dict[str, Any]:
        return {
            "id": node.id, "name": node.name, "status": node.status,
            "connector_version": node.connector_version,
            "last_heartbeat_at": node.last_heartbeat_at.isoformat() if node.last_heartbeat_at else None,
            "accounts": [
                {
                    "id": a.id, "nickname": a.nickname, "avatar_url": a.avatar_url,
                    "login_status": a.login_status,
                    "groups": [{"id": x.id, "name": x.name, "type": x.type} for x in a.groups.values()],
                    "contacts": [{"id": x.id, "name": x.name, "type": x.type} for x in a.contacts.values()],
                }
                for a in node.accounts.values()
            ],
        }

    async def bind_account(self, node_id: str, account_id: str, bot_id: str, enabled: bool) -> None:
        key = (node_id, account_id)
        async with self._lock:
            node = self._nodes.get(node_id)
            if enabled and (node is None or account_id not in node.accounts):
                raise ValueError("selected Windows node or WeChat account does not exist")
            existing = self._bindings.get(key)
            if enabled and existing and existing != bot_id:
                raise ValueError(f"WeChat account {account_id} on node {node_id} is already bound to bot {existing}")
            if enabled:
                self._bindings[key] = bot_id
            elif existing == bot_id:
                self._bindings.pop(key, None)
            self._save_state_locked()

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

    async def update_delivery_receipt(self, *, request_id: str, bot_id: str, node_id: str, status: str, detail: str = "") -> None:
        if not request_id:
            return
        async with self._lock:
            self._receipts[request_id] = DeliveryReceipt(request_id, bot_id, node_id, status, detail)

    async def get_delivery_receipt(self, request_id: str) -> dict[str, Any] | None:
        async with self._lock:
            r = self._receipts.get(request_id)
            return None if r is None else {
                "request_id": r.request_id, "bot_id": r.bot_id, "node_id": r.node_id,
                "status": r.status, "detail": r.detail, "updated_at": r.updated_at.isoformat(),
            }

    async def send_command(self, node_id: str, command: dict[str, Any]) -> None:
        async with self._lock:
            node = self._nodes.get(node_id)
            send = node.send if node and node.status == "online" else None
        if send is None:
            raise ConnectionError(f"wechat desktop node is offline: {node_id}")
        await send(command)


wechat_desktop_manager = WeChatDesktopManager()
