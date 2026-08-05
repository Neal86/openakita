from __future__ import annotations

from pathlib import Path

import pytest

from openakita.wechat_desktop.manager import WeChatDesktopManager


@pytest.mark.asyncio
async def test_pair_auth_persist_and_restore(tmp_path: Path) -> None:
    state = tmp_path / "nodes.json"
    manager = WeChatDesktopManager(state)
    code = await manager.create_pairing_code("客服电脑", ttl_seconds=600)
    node_id, token, node_name = await manager.consume_pairing_code(code)

    assert node_name == "客服电脑"
    assert await manager.authenticate_node(node_id, token) is True
    assert await manager.authenticate_node(node_id, token + "x") is False

    await manager.attach_node(node_id, node_token=token, send=_noop_send, connector_version="1.0.0")
    await manager.sync_accounts(
        node_id,
        [{"id": "wx-a", "nickname": "客服微信", "login_status": "logged_in"}],
    )
    await manager.sync_conversations(
        node_id,
        "wx-a",
        groups=[{"id": "group-a", "name": "客户群A"}],
        contacts=[{"id": "user-a", "name": "客户A"}],
    )
    await manager.bind_account(node_id, "wx-a", "bot-a", True)

    restored = WeChatDesktopManager(state)
    nodes = await restored.list_nodes()
    assert nodes[0]["id"] == node_id
    assert nodes[0]["status"] == "offline"
    assert nodes[0]["accounts"][0]["groups"][0]["id"] == "group-a"
    assert await restored.authenticate_node(node_id, token) is True

    with pytest.raises(ValueError, match="already bound"):
        await restored.bind_account(node_id, "wx-a", "bot-b", True)


@pytest.mark.asyncio
async def test_pairing_code_is_one_time(tmp_path: Path) -> None:
    manager = WeChatDesktopManager(tmp_path / "nodes.json")
    code = await manager.create_pairing_code("node")
    await manager.consume_pairing_code(code)
    with pytest.raises(ValueError, match="invalid or expired"):
        await manager.consume_pairing_code(code)


@pytest.mark.asyncio
async def test_node_token_has_no_time_expiry_and_manual_revoke_invalidates_it(tmp_path: Path) -> None:
    state = tmp_path / "nodes.json"
    manager = WeChatDesktopManager(state)
    code = await manager.create_pairing_code("node")
    node_id, token, _ = await manager.consume_pairing_code(code)

    restored = WeChatDesktopManager(state)
    assert await restored.authenticate_node(node_id, token) is True
    assert await restored.revoke_node(node_id) is True
    assert await restored.authenticate_node(node_id, token) is False

    restarted_after_revoke = WeChatDesktopManager(state)
    assert await restarted_after_revoke.authenticate_node(node_id, token) is False


async def _noop_send(_payload: dict) -> None:
    return None
