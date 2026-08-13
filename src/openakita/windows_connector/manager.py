from __future__ import annotations

import asyncio
import json
import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
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


@contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            if path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


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
        if not isinstance(raw, dict):
            raise ValueError("resource row must be an object")
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
    sync_state: str = "synced"
    sync_error: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AgentResourceGrant:
        if not isinstance(raw, dict):
            raise ValueError("grant row must be an object")
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
        self._remote_connections: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._local_execution_lock = asyncio.Lock()
        self._local_executor = WindowsCommandExecutor()
        self._migrate_legacy_state()
        self._load()

    @property
    def _backup_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".bak")

    @property
    def _lock_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".lock")

    def _migrate_legacy_state(self) -> None:
        if (
            self.path.exists()
            or self.path == LEGACY_STATE_PATH
            or not LEGACY_STATE_PATH.exists()
        ):
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_name(
                f".{self.path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
            )
            try:
                shutil.copy2(LEGACY_STATE_PATH, temp)
                os.replace(temp, self.path)
            finally:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass
        except OSError:
            pass

    @property
    def local_available(self) -> bool:
        return os.name == "nt"

    @staticmethod
    def _decode_state(
        path: Path,
    ) -> tuple[
        dict[str, AgentResourceGrant], dict[str, dict[str, WindowsResource]]
    ]:
        raw = json.loads(path.read_text("utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("state root must be an object")
        grants: dict[str, AgentResourceGrant] = {}
        grant_rows = raw.get("grants", [])
        for row in grant_rows if isinstance(grant_rows, list) else []:
            try:
                grant = AgentResourceGrant.from_dict(row)
                if (
                    grant.id
                    and grant.node_id
                    and grant.agent_profile_id
                    and grant.resource_id
                ):
                    grants[grant.id] = grant
            except (TypeError, ValueError):
                continue
        resources: dict[str, dict[str, WindowsResource]] = {}
        resource_root = raw.get("resources") or {}
        if isinstance(resource_root, dict):
            for node_id, rows in resource_root.items():
                if not isinstance(rows, list):
                    continue
                decoded: dict[str, WindowsResource] = {}
                for row in rows:
                    try:
                        item = WindowsResource.from_dict(row)
                        if item.id and item.fingerprint:
                            decoded[item.id] = item
                    except (TypeError, ValueError):
                        continue
                resources[str(node_id)] = decoded
        return grants, resources

    def _load(self) -> None:
        for candidate in (self.path, self._backup_path):
            if not candidate.exists():
                continue
            try:
                grants, resources = self._decode_state(candidate)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            self._grants = grants
            self._resources = resources
            return

    def _main_state_is_valid(self) -> bool:
        if not self.path.exists():
            return False
        try:
            self._decode_state(self.path)
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        return True

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 4,
            "grants": [asdict(grant) for grant in self._grants.values()],
            "resources": {
                node_id: [asdict(resource) for resource in rows.values()]
                for node_id, rows in self._resources.items()
            },
        }
        encoded = json.dumps(payload, ensure_ascii=False, indent=2)
        with _exclusive_file_lock(self._lock_path):
            # Never replace a known-good backup with a corrupted primary file.
            # This matters after startup has recovered successfully from .bak.
            if self._main_state_is_valid():
                try:
                    self._backup_path.write_bytes(self.path.read_bytes())
                except OSError:
                    pass
            tmp = self.path.with_name(
                f".{self.path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
            )
            try:
                tmp.write_text(encoded, "utf-8")
                os.replace(tmp, self.path)
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass

    async def begin_remote_connection(self, node_id: str, connection_id: str) -> None:
        if not node_id or not connection_id:
            raise ValueError("node_id and connection_id are required")
        async with self._lock:
            self._remote_connections[node_id] = connection_id

    async def end_remote_connection(self, node_id: str, connection_id: str) -> None:
        async with self._lock:
            if self._remote_connections.get(node_id) == connection_id:
                self._remote_connections.pop(node_id, None)

    async def sync_resources(
        self,
        node_id: str,
        rows: list[dict[str, Any]],
        *,
        connection_id: str = "",
    ) -> None:
        synced: dict[str, WindowsResource] = {}
        for raw in rows:
            try:
                item = WindowsResource.from_dict(raw)
            except (TypeError, ValueError):
                continue
            if not item.id or not item.fingerprint:
                continue
            item.updated_at = datetime.now(UTC).isoformat()
            synced[item.id] = item
        async with self._lock:
            if (
                node_id != LOCAL_NODE_ID
                and connection_id
                and self._remote_connections.get(node_id) != connection_id
            ):
                raise ConnectionError("stale connector resource sync")
            self._resources[node_id] = synced
            self._save_locked()

    async def refresh_local_resources(self) -> list[dict[str, Any]]:
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

    async def _set_sync_state(
        self, node_id: str, state: str, error: str = ""
    ) -> None:
        async with self._lock:
            changed = False
            for grant in self._grants.values():
                if grant.node_id == node_id:
                    grant.sync_state = state
                    grant.sync_error = error
                    changed = True
            if changed:
                self._save_locked()

    async def upsert_grant(self, raw: dict[str, Any]) -> dict[str, Any]:
        node_id = str(raw.get("node_id") or "").strip()
        agent_id = str(raw.get("agent_profile_id") or "").strip()
        resource_id = str(raw.get("resource_id") or "").strip()
        if not node_id or not agent_id or not resource_id:
            raise ValueError(
                "node_id, agent_profile_id and resource_id are required"
            )
        async with self._lock:
            resource = self._resources.get(node_id, {}).get(resource_id)
            if resource is None:
                raise ValueError(
                    "selected Windows resource is not currently available"
                )
            stable_identity = resource.stable_identity or resource.fingerprint
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
            permissions = raw.get("permissions") or {}
            grant = AgentResourceGrant(
                id=existing.id if existing else f"grant-{secrets.token_hex(12)}",
                node_id=node_id,
                agent_profile_id=agent_id,
                resource_id=resource.id,
                fingerprint=resource.fingerprint,
                stable_identity=stable_identity,
                remark=str(
                    raw.get("remark") or (existing.remark if existing else "")
                ).strip(),
                read=bool(permissions.get("read", raw.get("read", True))),
                screenshot=bool(
                    permissions.get("screenshot", raw.get("screenshot", True))
                ),
                mouse=bool(permissions.get("mouse", raw.get("mouse", False))),
                keyboard=bool(
                    permissions.get("keyboard", raw.get("keyboard", False))
                ),
                launch=bool(permissions.get("launch", raw.get("launch", False))),
                close=bool(permissions.get("close", raw.get("close", False))),
                created_at=(
                    existing.created_at
                    if existing
                    else datetime.now(UTC).isoformat()
                ),
                sync_state="synced" if node_id == LOCAL_NODE_ID else "pending",
                sync_error="",
            )
            self._grants[grant.id] = grant
            self._save_locked()
        await self.push_permissions(node_id)
        async with self._lock:
            return self._grant_dict(self._grants[grant.id])

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
            if grant.node_id != LOCAL_NODE_ID:
                grant.sync_state = "pending"
                grant.sync_error = ""
            self._save_locked()
        await self.push_permissions(grant.node_id)
        async with self._lock:
            return self._grant_dict(self._grants[grant_id])

    async def permission_snapshot(self, node_id: str) -> list[dict[str, Any]]:
        async with self._lock:
            return [
                self._grant_dict(grant)
                for grant in self._grants.values()
                if grant.node_id == node_id
            ]

    async def push_permissions(self, node_id: str) -> bool:
        snapshot = await self.permission_snapshot(node_id)
        if node_id == LOCAL_NODE_ID:
            self._local_executor.sync_grants(snapshot)
            await self._set_sync_state(node_id, "synced")
            return True
        try:
            await wechat_desktop_manager.send_command(
                node_id,
                {
                    "version": 1,
                    "event": "windows.permissions.sync",
                    "payload": {"grants": snapshot},
                },
            )
        except ConnectionError as exc:
            await self._set_sync_state(node_id, "pending", str(exc))
            return False
        await self._set_sync_state(node_id, "synced")
        return True

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
            candidates = [
                grant
                for grant in self._grants.values()
                if grant.node_id == node_id
                and grant.agent_profile_id == agent_profile_id
                and grant.resource_id == resource.id
            ]
            if not candidates:
                identity = resource.stable_identity or resource.fingerprint
                collisions = [
                    item
                    for item in resources.values()
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
            raise PermissionError(
                "Agent is not authorized for this Windows resource"
            )
        grant = candidates[0]
        permission = self.ACTION_PERMISSION.get(action)
        if permission is None:
            raise PermissionError(
                f"unsupported Windows Connector action: {action}"
            )
        if not grant.permissions().get(permission, False):
            raise PermissionError(
                f"Agent grant does not allow {permission} for action {action}"
            )
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
        grant, resource = await self._resolve_grant(
            node_id, agent_profile_id, resource_id, action
        )
        payload = {
            "agent_profile_id": agent_profile_id,
            "resource_id": resource.id,
            "resource_fingerprint": resource.fingerprint,
            "resource_stable_identity": (
                resource.stable_identity or resource.fingerprint
            ),
            "grant_id": grant.id,
            "action": action,
            "arguments": arguments or {},
        }
        if node_id == LOCAL_NODE_ID:
            async with self._local_execution_lock:
                self._local_executor.sync_grants(
                    await self.permission_snapshot(LOCAL_NODE_ID)
                )

                def run_local() -> dict[str, Any]:
                    return asyncio.run(self._local_executor.execute(payload))

                worker = asyncio.create_task(asyncio.to_thread(run_local))
                try:
                    return await asyncio.wait_for(
                        asyncio.shield(worker), timeout=timeout
                    )
                except asyncio.CancelledError:
                    # Thread cancellation cannot safely stop an in-flight Windows
                    # UI action. Keep the lock until it truly ends, then propagate.
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        await worker
                    raise
                except TimeoutError:
                    # Hold the execution lock until the Windows API call really
                    # ends so a later command can never overlap it.
                    await worker
                    raise

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

    async def handle_result(
        self,
        node_id: str,
        request_id: str,
        payload: dict[str, Any],
        *,
        connection_id: str = "",
    ) -> None:
        async with self._lock:
            if (
                connection_id
                and self._remote_connections.get(node_id) != connection_id
            ):
                raise ConnectionError("stale connector command result")
            pending = self._pending.get(request_id)
        if pending is None:
            return
        expected_node_id, future = pending
        if expected_node_id != node_id:
            return
        if not future.done():
            future.set_result(payload)


windows_connector_manager = WindowsConnectorManager()
