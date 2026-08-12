from __future__ import annotations

import asyncio
import json
import os
import secrets
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openakita.wechat_desktop import wechat_desktop_manager

from .executor import WindowsCommandExecutor


def _default_state_path() -> Path:
    explicit = os.environ.get("OPENAKITA_DATA_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve() / "windows_connector" / "state.json"
    return Path.home() / ".openakita" / "data" / "windows_connector" / "state.json"


STATE_PATH = _default_state_path()
LEGACY_STATE_PATH = Path("data/windows_connector/state.json")
LOCAL_NODE_ID = "local"


@dataclass(slots=True)
class WindowsResource:
    id: str
    fingerprint: str
    kind: str
    app_name: str
    stable_identity: str = ""
    volatile_window_id: str = ""
    process_name: str = ""
    pid: int = 0
    hwnd: int = 0
    title: str = ""
    exe_path: str = ""
    account_name: str = ""
    browser_profile: str = ""
    tab_id: str = ""
    url: str = ""
    automation: str = "uia"
    controllable: bool = True
    limited: bool = False
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> WindowsResource:
        known = cls.__dataclass_fields__
        return cls(**{key: value for key, value in raw.items() if key in known})


@dataclass(slots=True)
class AgentResourceGrant:
    id: str
    node_id: str
    agent_profile_id: str
    resource_id: str
    fingerprint: str
    stable_identity: str = ""
    remark: str = ""
    read: bool = True
    screenshot: bool = True
    mouse: bool = False
    keyboard: bool = False
    launch: bool = False
    close: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AgentResourceGrant:
        known = cls.__dataclass_fields__
        return cls(**{key: value for key, value in raw.items() if key in known})

    def permissions(self) -> dict[str, bool]:
        return {
            "read": self.read,
            "screenshot": self.screenshot,
            "mouse": self.mouse,
            "keyboard": self.keyboard,
            "launch": self.launch,
            "close": self.close,
        }


class WindowsConnectorManager:
    """Unified registry for local and remote Windows application resources."""

    ACTION_PERMISSION = {
        "list": "read",
        "inspect": "read",
        "read_ui": "read",
        "browser_read": "read",
        "screenshot": "screenshot",
        "focus": "mouse",
        "click": "mouse",
        "double_click": "mouse",
        "scroll": "mouse",
        "browser_click": "mouse",
        "type": "keyboard",
        "hotkey": "keyboard",
        "browser_type": "keyboard",
        "browser_navigate": "keyboard",
        "launch": "launch",
        "close": "close",
    }

    def __init__(self, path: Path = STATE_PATH) -> None:
        self.path = path
        self._resources: dict[str, dict[str, WindowsResource]] = {}
        self._grants: dict[str, AgentResourceGrant] = {}
        self._pending: dict[str, tuple[str, asyncio.Future[dict[str, Any]]]] = {}
        self._lock = asyncio.Lock()
        self._local_executor = WindowsCommandExecutor()
        self._migrate_legacy_state()
        self._load()

    def _migrate_legacy_state(self) -> None:
        if self.path.exists() or self.path == LEGACY_STATE_PATH or not LEGACY_STATE_PATH.exists():
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_bytes(LEGACY_STATE_PATH.read_bytes())
        except OSError:
            pass

    @property
    def local_available(self) -> bool:
        return os.name == "nt"

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text("utf-8"))
            for row in raw.get("grants", []):
                grant = AgentResourceGrant.from_dict(row)
                self._grants[grant.id] = grant
            for node_id, rows in (raw.get("resources") or {}).items():
                self._resources[str(node_id)] = {
                    item.id: item for item in (WindowsResource.from_dict(row) for row in rows)
                }
        except Exception:
            self._grants = {}
            self._resources = {}

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 3,
            "grants": [asdict(grant) for grant in self._grants.values()],
            "resources": {
                node_id: [asdict(resource) for resource in rows.values()]
                for node_id, rows in self._resources.items()
            },
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(self.path)

    async def sync_resources(self, node_id: str, rows: list[dict[str, Any]]) -> None:
        synced: dict[str, WindowsResource] = {}
        for raw in rows:
            try:
                item = WindowsResource.from_dict(raw)
            except Exception:
                continue
            if not item.id or not item.fingerprint:
                continue
            item.updated_at = datetime.now(UTC).isoformat()
            synced[item.id] = item
        async with self._lock:
            self._resources[node_id] = synced
            self._save_locked()

    async def refresh_local_resources(self) -> list[dict[str, Any]]:
        """Discover local apps without requiring a separately installed connector."""
        if not self.local_available:
            await self.sync_resources(LOCAL_NODE_ID, [])
            return []
        rows = await asyncio.to_thread(self._local_executor.resources)
        await self.sync_resources(LOCAL_NODE_ID, rows)
        return await self.list_resources(LOCAL_NODE_ID)

    async def local_node(self, *, refresh: bool = False) -> dict[str, Any]:
        if refresh:
            await self.refresh_local_resources()
        return {
            "id": LOCAL_NODE_ID,
            "name": "本机",
            "status": "online" if self.local_available else "unsupported",
            "connector_version": "embedded",
            "transport": "local",
            "embedded": True,
            "resources": await self.list_resources(LOCAL_NODE_ID),
            "grants": await self.list_grants(LOCAL_NODE_ID),
        }

    async def list_resources(self, node_id: str) -> list[dict[str, Any]]:
        async with self._lock:
            rows = list(self._resources.get(node_id, {}).values())
            grants = list(self._grants.values())
        identity_counts: dict[str, int] = {}
        for item in rows:
            identity = item.stable_identity or item.fingerprint
            identity_counts[identity] = identity_counts.get(identity, 0) + 1
        result: list[dict[str, Any]] = []
        for item in rows:
            identity = item.stable_identity or item.fingerprint
            raw = asdict(item)
            raw["grants"] = [
                self._grant_dict(grant)
                for grant in grants
                if grant.node_id == node_id
                and (
                    grant.resource_id == item.id
                    or (
                        identity_counts.get(identity) == 1
                        and (grant.stable_identity or grant.fingerprint) == identity
                    )
                )
            ]
            result.append(raw)
        return result

    async def list_grants(self, node_id: str | None = None) -> list[dict[str, Any]]:
        async with self._lock:
            grants = list(self._grants.values())
        if node_id:
            grants = [grant for grant in grants if grant.node_id == node_id]
        return [self._grant_dict(grant) for grant in grants]

    @staticmethod
    def _grant_dict(grant: AgentResourceGrant) -> dict[str, Any]:
        raw = asdict(grant)
        raw["permissions"] = grant.permissions()
        return raw

    async def upsert_grant(self, raw: dict[str, Any]) -> dict[str, Any]:
        node_id = str(raw.get("node_id") or "").strip()
        agent_id = str(raw.get("agent_profile_id") or "").strip()
        resource_id = str(raw.get("resource_id") or "").strip()
        if not node_id or not agent_id or not resource_id:
            raise ValueError("node_id, agent_profile_id and resource_id are required")
        async with self._lock:
            resource = self._resources.get(node_id, {}).get(resource_id)
            if resource is None:
                raise ValueError("selected Windows resource is not currently available")
            stable_identity = resource.stable_identity or resource.fingerprint
            explicit_id = str(raw.get("id") or "").strip()
            existing = next(
                (
                    grant
                    for grant in self._grants.values()
                    if grant.node_id == node_id
                    and grant.agent_profile_id == agent_id
                    and (grant.stable_identity or grant.fingerprint) == stable_identity
                ),
                None,
            )
            grant_id = explicit_id or (existing.id if existing else f"grant-{secrets.token_hex(6)}")
            permissions = raw.get("permissions") or {}
            grant = AgentResourceGrant(
                id=grant_id,
                node_id=node_id,
                agent_profile_id=agent_id,
                resource_id=resource.id,
                fingerprint=resource.fingerprint,
                stable_identity=stable_identity,
                remark=str(raw.get("remark") or (existing.remark if existing else "")).strip(),
                read=bool(permissions.get("read", raw.get("read", True))),
                screenshot=bool(permissions.get("screenshot", raw.get("screenshot", True))),
                mouse=bool(permissions.get("mouse", raw.get("mouse", False))),
                keyboard=bool(permissions.get("keyboard", raw.get("keyboard", False))),
                launch=bool(permissions.get("launch", raw.get("launch", False))),
                close=bool(permissions.get("close", raw.get("close", False))),
                created_at=existing.created_at if existing else datetime.now(UTC).isoformat(),
            )
            if existing and existing.id != grant_id:
                self._grants.pop(existing.id, None)
            self._grants[grant.id] = grant
            self._save_locked()
        await self.push_permissions(node_id)
        return self._grant_dict(grant)

    async def delete_grant(self, grant_id: str) -> bool:
        async with self._lock:
            grant = self._grants.pop(grant_id, None)
            if grant is None:
                return False
            self._save_locked()
        await self.push_permissions(grant.node_id)
        return True

    async def set_remark(self, grant_id: str, remark: str) -> dict[str, Any]:
        async with self._lock:
            grant = self._grants.get(grant_id)
            if grant is None:
                raise KeyError(grant_id)
            grant.remark = remark.strip()
            self._save_locked()
            raw = self._grant_dict(grant)
        await self.push_permissions(grant.node_id)
        return raw

    async def permission_snapshot(self, node_id: str) -> list[dict[str, Any]]:
        async with self._lock:
            return [
                self._grant_dict(grant)
                for grant in self._grants.values()
                if grant.node_id == node_id
            ]

    async def push_permissions(self, node_id: str) -> None:
        snapshot = await self.permission_snapshot(node_id)
        if node_id == LOCAL_NODE_ID:
            self._local_executor.sync_grants(snapshot)
            return
        try:
            await wechat_desktop_manager.send_command(
                node_id,
                {"version": 1, "event": "windows.permissions.sync", "payload": {"grants": snapshot}},
            )
        except ConnectionError:
            pass

    async def commands_for_attach(self, node_id: str) -> list[dict[str, Any]]:
        if node_id == LOCAL_NODE_ID:
            return []
        return [
            {
                "version": 1,
                "event": "windows.permissions.sync",
                "payload": {"grants": await self.permission_snapshot(node_id)},
            },
            {"version": 1, "event": "windows.resources.refresh", "payload": {}},
        ]

    async def _resolve_grant(
        self,
        node_id: str,
        agent_profile_id: str,
        resource_id: str,
        action: str,
    ) -> tuple[AgentResourceGrant, WindowsResource]:
        async with self._lock:
            resources = self._resources.get(node_id, {})
            resource = resources.get(resource_id)
            if resource is None:
                raise PermissionError("Windows resource is offline or unknown")
            exact = [
                grant
                for grant in self._grants.values()
                if grant.node_id == node_id
                and grant.agent_profile_id == agent_profile_id
                and grant.resource_id == resource.id
            ]
            candidates = exact
            if not candidates:
                identity = resource.stable_identity or resource.fingerprint
                collisions = [
                    item for item in resources.values()
                    if (item.stable_identity or item.fingerprint) == identity
                ]
                if len(collisions) == 1:
                    candidates = [
                        grant
                        for grant in self._grants.values()
                        if grant.node_id == node_id
                        and grant.agent_profile_id == agent_profile_id
                        and (grant.stable_identity or grant.fingerprint) == identity
                    ]
        if not candidates:
            raise PermissionError("Agent is not authorized for this Windows resource")
        grant = candidates[0]
        permission = self.ACTION_PERMISSION.get(action)
        if permission is None:
            raise PermissionError(f"unsupported Windows Connector action: {action}")
        if not grant.permissions().get(permission, False):
            raise PermissionError(f"Agent grant does not allow {permission} for action {action}")
        return grant, resource

    async def execute(
        self,
        *,
        node_id: str,
        agent_profile_id: str,
        resource_id: str,
        action: str,
        arguments: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        grant, resource = await self._resolve_grant(node_id, agent_profile_id, resource_id, action)
        payload = {
            "agent_profile_id": agent_profile_id,
            "resource_id": resource.id,
            "resource_fingerprint": resource.fingerprint,
            "grant_id": grant.id,
            "action": action,
            "arguments": arguments or {},
        }
        if node_id == LOCAL_NODE_ID:
            self._local_executor.sync_grants(await self.permission_snapshot(LOCAL_NODE_ID))
            return await asyncio.wait_for(self._local_executor.execute(payload), timeout=timeout)

        request_id = f"wc-{secrets.token_hex(8)}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        async with self._lock:
            self._pending[request_id] = (node_id, future)
        command = {
            "version": 1,
            "event": "windows.command",
            "request_id": request_id,
            "payload": payload,
        }
        try:
            await wechat_desktop_manager.send_command(node_id, command)
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            async with self._lock:
                self._pending.pop(request_id, None)

    async def handle_result(self, node_id: str, request_id: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            pending = self._pending.get(request_id)
        if pending is None:
            return
        expected_node_id, future = pending
        if expected_node_id != node_id:
            return
        if not future.done():
            future.set_result(payload)


windows_connector_manager = WindowsConnectorManager()
