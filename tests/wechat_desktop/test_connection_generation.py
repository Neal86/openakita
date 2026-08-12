import asyncio

import pytest

from openakita.wechat_desktop.manager import WeChatDesktopManager
from openakita.windows_connector.manager import WindowsConnectorManager


async def _noop_send(_payload):
    return None


@pytest.mark.asyncio
async def test_old_wechat_connection_cannot_overwrite_new_state(tmp_path):
    manager = WeChatDesktopManager(tmp_path / "wechat.json")
    code = await manager.create_pairing_code("PC")
    node_id, token, _ = await manager.consume_pairing_code(code)
    await manager.attach_node(
        node_id, node_token=token, send=_noop_send, connection_id="old"
    )
    await manager.attach_node(
        node_id, node_token=token, send=_noop_send, connection_id="new"
    )

    with pytest.raises(ConnectionError, match="stale connector"):
        await manager.sync_accounts(
            node_id, [{"id": "old-account"}], connection_id="old"
        )
    await manager.sync_accounts(
        node_id, [{"id": "new-account"}], connection_id="new"
    )
    node = await manager.get_node(node_id)
    assert [row["id"] for row in node["accounts"]] == ["new-account"]


@pytest.mark.asyncio
async def test_old_windows_connection_cannot_sync_resources_or_results(tmp_path):
    manager = WindowsConnectorManager(tmp_path / "windows.json")
    await manager.begin_remote_connection("node", "old")
    await manager.begin_remote_connection("node", "new")

    row = {
        "id": "window-1",
        "fingerprint": "fp-1",
        "kind": "window",
        "app_name": "App",
    }
    with pytest.raises(ConnectionError, match="stale connector"):
        await manager.sync_resources("node", [row], connection_id="old")
    await manager.sync_resources("node", [row], connection_id="new")
    assert [item["id"] for item in await manager.list_resources("node")] == ["window-1"]

    future = asyncio.get_running_loop().create_future()
    manager._pending["req"] = ("node", future)
    with pytest.raises(ConnectionError, match="stale connector"):
        await manager.handle_result(
            "node", "req", {"ok": False}, connection_id="old"
        )
    assert not future.done()
    await manager.handle_result(
        "node", "req", {"ok": True}, connection_id="new"
    )
    assert (await future)["ok"] is True
