from pathlib import Path


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text("utf-8")
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"{label} marker changed")
    path.write_text(text.replace(old, new, 1), "utf-8")


def main() -> None:
    wechat = Path("src/openakita/wechat_desktop/manager.py")
    replace_exact(
        wechat,
        '''    async def authenticate_node(self, node_id: str, node_token: str) -> bool:\n        async with self._lock:\n            node = self._nodes.get(node_id)\n            expected = node.token_hash if node else ""\n        return bool(expected) and secrets.compare_digest(expected, self._hash(node_token))\n\n    async def revoke_node''',
        '''    async def authenticate_node(self, node_id: str, node_token: str) -> bool:\n        async with self._lock:\n            node = self._nodes.get(node_id)\n            expected = node.token_hash if node else ""\n        return bool(expected) and secrets.compare_digest(expected, self._hash(node_token))\n\n    async def assert_current_connection(self, node_id: str, connection_id: str) -> None:\n        """Reject events from a socket that has already been superseded."""\n        async with self._lock:\n            node = self._nodes.get(node_id)\n            if (\n                node is None\n                or not connection_id\n                or node.connection_id != connection_id\n                or node.send is None\n            ):\n                raise ConnectionError("connector session has been replaced or disconnected")\n\n    async def revoke_node''',
        "current connection guard",
    )
    replace_exact(
        wechat,
        '''    async def heartbeat(self, node_id: str) -> None:\n        async with self._lock:\n            node = self._nodes.get(node_id)\n            if node:\n                node.status = "online"\n                node.last_heartbeat_at = datetime.now(UTC)\n\n    async def sync_accounts(self, node_id: str, accounts: list[dict[str, Any]]) -> None:\n        async with self._lock:\n            node = self._nodes.get(node_id)\n            if node is None:\n                raise ValueError("unknown connector node")\n''',
        '''    async def heartbeat(self, node_id: str, *, connection_id: str = "") -> None:\n        async with self._lock:\n            node = self._nodes.get(node_id)\n            if node is None:\n                return\n            if connection_id and node.connection_id != connection_id:\n                raise ConnectionError("stale connector heartbeat")\n            node.status = "online"\n            node.last_heartbeat_at = datetime.now(UTC)\n\n    async def sync_accounts(\n        self,\n        node_id: str,\n        accounts: list[dict[str, Any]],\n        *,\n        connection_id: str = "",\n    ) -> None:\n        async with self._lock:\n            node = self._nodes.get(node_id)\n            if node is None:\n                raise ValueError("unknown connector node")\n            if connection_id and node.connection_id != connection_id:\n                raise ConnectionError("stale connector account sync")\n''',
        "heartbeat/account generation guard",
    )
    replace_exact(
        wechat,
        '''    async def sync_conversations(\n        self,\n        node_id: str,\n        account_id: str,\n        *,\n        groups: list[dict[str, Any]],\n        contacts: list[dict[str, Any]],\n    ) -> None:\n        async with self._lock:\n            node = self._nodes.get(node_id)\n            account = node.accounts.get(account_id) if node else None\n            if account is None:\n                raise ValueError("unknown WeChat account")\n''',
        '''    async def sync_conversations(\n        self,\n        node_id: str,\n        account_id: str,\n        *,\n        groups: list[dict[str, Any]],\n        contacts: list[dict[str, Any]],\n        connection_id: str = "",\n    ) -> None:\n        async with self._lock:\n            node = self._nodes.get(node_id)\n            if node is not None and connection_id and node.connection_id != connection_id:\n                raise ConnectionError("stale connector conversation sync")\n            account = node.accounts.get(account_id) if node else None\n            if account is None:\n                raise ValueError("unknown WeChat account")\n''',
        "conversation generation guard",
    )

    windows = Path("src/openakita/windows_connector/manager.py")
    replace_exact(
        windows,
        '''        self._resources: dict[str, dict[str, WindowsResource]] = {}\n        self._grants: dict[str, AgentResourceGrant] = {}\n        self._pending: dict[str, tuple[str, asyncio.Future[dict[str, Any]]]] = {}\n        self._lock = asyncio.Lock()\n''',
        '''        self._resources: dict[str, dict[str, WindowsResource]] = {}\n        self._grants: dict[str, AgentResourceGrant] = {}\n        self._pending: dict[str, tuple[str, asyncio.Future[dict[str, Any]]]] = {}\n        self._remote_connections: dict[str, str] = {}\n        self._lock = asyncio.Lock()\n''',
        "remote connection registry",
    )
    replace_exact(
        windows,
        '''    async def sync_resources(self, node_id: str, rows: list[dict[str, Any]]) -> None:\n        synced: dict[str, WindowsResource] = {}\n''',
        '''    async def begin_remote_connection(self, node_id: str, connection_id: str) -> None:\n        if not node_id or not connection_id:\n            raise ValueError("node_id and connection_id are required")\n        async with self._lock:\n            self._remote_connections[node_id] = connection_id\n\n    async def end_remote_connection(self, node_id: str, connection_id: str) -> None:\n        async with self._lock:\n            if self._remote_connections.get(node_id) == connection_id:\n                self._remote_connections.pop(node_id, None)\n\n    async def sync_resources(\n        self,\n        node_id: str,\n        rows: list[dict[str, Any]],\n        *,\n        connection_id: str = "",\n    ) -> None:\n        synced: dict[str, WindowsResource] = {}\n''',
        "windows connection lifecycle",
    )
    replace_exact(
        windows,
        '''        async with self._lock:\n            self._resources[node_id] = synced\n            self._save_locked()\n\n    async def refresh_local_resources''',
        '''        async with self._lock:\n            if (\n                node_id != LOCAL_NODE_ID\n                and connection_id\n                and self._remote_connections.get(node_id) != connection_id\n            ):\n                raise ConnectionError("stale connector resource sync")\n            self._resources[node_id] = synced\n            self._save_locked()\n\n    async def refresh_local_resources''',
        "resource generation guard",
    )
    replace_exact(
        windows,
        '''    async def handle_result(\n        self, node_id: str, request_id: str, payload: dict[str, Any]\n    ) -> None:\n        async with self._lock:\n            pending = self._pending.get(request_id)\n''',
        '''    async def handle_result(\n        self,\n        node_id: str,\n        request_id: str,\n        payload: dict[str, Any],\n        *,\n        connection_id: str = "",\n    ) -> None:\n        async with self._lock:\n            if (\n                connection_id\n                and self._remote_connections.get(node_id) != connection_id\n            ):\n                raise ConnectionError("stale connector command result")\n            pending = self._pending.get(request_id)\n''',
        "result generation guard",
    )

    route = Path("src/openakita/api/routes/wechat_desktop.py")
    replace_exact(
        route,
        '''    await wechat_desktop_manager.attach_node(\n        node_id,\n        node_token=node_token,\n        send=send,\n        connector_version=connector_version,\n        connection_id=connection_id,\n    )\n\n    try:\n''',
        '''    await wechat_desktop_manager.attach_node(\n        node_id,\n        node_token=node_token,\n        send=send,\n        connector_version=connector_version,\n        connection_id=connection_id,\n    )\n    await windows_connector_manager.begin_remote_connection(node_id, connection_id)\n\n    try:\n''',
        "route connection registration",
    )
    replace_exact(
        route,
        '''            try:\n                if event == "node.heartbeat":\n                    await wechat_desktop_manager.heartbeat(node_id)\n                elif event == "windows.resources.sync":\n                    await windows_connector_manager.sync_resources(\n                        node_id, payload.get("resources") or []\n                    )\n''',
        '''            try:\n                await wechat_desktop_manager.assert_current_connection(\n                    node_id, connection_id\n                )\n                if event == "node.heartbeat":\n                    await wechat_desktop_manager.heartbeat(\n                        node_id, connection_id=connection_id\n                    )\n                elif event == "windows.resources.sync":\n                    await windows_connector_manager.sync_resources(\n                        node_id,\n                        payload.get("resources") or [],\n                        connection_id=connection_id,\n                    )\n''',
        "route event generation guard",
    )
    replace_exact(
        route,
        '''                        await windows_connector_manager.handle_result(\n                            node_id, request_id, payload\n                        )\n''',
        '''                        await windows_connector_manager.handle_result(\n                            node_id,\n                            request_id,\n                            payload,\n                            connection_id=connection_id,\n                        )\n''',
        "route result generation",
    )
    replace_exact(
        route,
        '''                    await wechat_desktop_manager.sync_accounts(\n                        node_id, payload.get("accounts") or []\n                    )\n''',
        '''                    await wechat_desktop_manager.sync_accounts(\n                        node_id,\n                        payload.get("accounts") or [],\n                        connection_id=connection_id,\n                    )\n''',
        "route account generation",
    )
    replace_exact(
        route,
        '''                        groups=payload.get("groups") or [],\n                        contacts=payload.get("contacts") or [],\n                    )\n''',
        '''                        groups=payload.get("groups") or [],\n                        contacts=payload.get("contacts") or [],\n                        connection_id=connection_id,\n                    )\n''',
        "route conversation generation",
    )
    replace_exact(
        route,
        '''    finally:\n        await wechat_desktop_manager.detach_node(\n            node_id, connection_id=connection_id\n        )\n''',
        '''    finally:\n        await windows_connector_manager.end_remote_connection(node_id, connection_id)\n        await wechat_desktop_manager.detach_node(\n            node_id, connection_id=connection_id\n        )\n''',
        "route connection cleanup",
    )

    test = Path("tests/wechat_desktop/test_connection_generation.py")
    test.write_text(
        '''import asyncio\n\nimport pytest\n\nfrom openakita.wechat_desktop.manager import WeChatDesktopManager\nfrom openakita.windows_connector.manager import WindowsConnectorManager\n\n\nasync def _noop_send(_payload):\n    return None\n\n\n@pytest.mark.asyncio\nasync def test_old_wechat_connection_cannot_overwrite_new_state(tmp_path):\n    manager = WeChatDesktopManager(tmp_path / "wechat.json")\n    code = await manager.create_pairing_code("PC")\n    node_id, token, _ = await manager.consume_pairing_code(code)\n    await manager.attach_node(\n        node_id, node_token=token, send=_noop_send, connection_id="old"\n    )\n    await manager.attach_node(\n        node_id, node_token=token, send=_noop_send, connection_id="new"\n    )\n\n    with pytest.raises(ConnectionError, match="stale connector"):\n        await manager.sync_accounts(\n            node_id, [{"id": "old-account"}], connection_id="old"\n        )\n    await manager.sync_accounts(\n        node_id, [{"id": "new-account"}], connection_id="new"\n    )\n    node = await manager.get_node(node_id)\n    assert [row["id"] for row in node["accounts"]] == ["new-account"]\n\n\n@pytest.mark.asyncio\nasync def test_old_windows_connection_cannot_sync_resources_or_results(tmp_path):\n    manager = WindowsConnectorManager(tmp_path / "windows.json")\n    await manager.begin_remote_connection("node", "old")\n    await manager.begin_remote_connection("node", "new")\n\n    row = {\n        "id": "window-1",\n        "fingerprint": "fp-1",\n        "kind": "window",\n        "app_name": "App",\n    }\n    with pytest.raises(ConnectionError, match="stale connector"):\n        await manager.sync_resources("node", [row], connection_id="old")\n    await manager.sync_resources("node", [row], connection_id="new")\n    assert [item["id"] for item in await manager.list_resources("node")] == ["window-1"]\n\n    future = asyncio.get_running_loop().create_future()\n    manager._pending["req"] = ("node", future)\n    with pytest.raises(ConnectionError, match="stale connector"):\n        await manager.handle_result(\n            "node", "req", {"ok": False}, connection_id="old"\n        )\n    assert not future.done()\n    await manager.handle_result(\n        "node", "req", {"ok": True}, connection_id="new"\n    )\n    assert (await future)["ok"] is True\n''',
        "utf-8",
    )


if __name__ == "__main__":
    main()
