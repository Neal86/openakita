from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openakita.wechat_desktop.manager import (
    DeliveryReceipt,
    PairingTicket,
    WeChatDesktopManager,
)


@pytest.mark.asyncio
async def test_create_pairing_code_prunes_expired_ticket(tmp_path: Path):
    manager = WeChatDesktopManager(tmp_path / "nodes.json")
    manager._pairings["expired"] = PairingTicket(
        code_hash="expired",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
        node_name="old",
    )

    code = await manager.create_pairing_code("new")

    assert "expired" not in manager._pairings
    assert manager._hash(code) in manager._pairings


@pytest.mark.asyncio
async def test_delivery_receipts_prune_expired_and_bound_size(tmp_path: Path, monkeypatch):
    manager = WeChatDesktopManager(tmp_path / "nodes.json")
    monkeypatch.setattr("openakita.wechat_desktop.manager.DELIVERY_RECEIPT_MAX", 2)
    manager._receipts["expired"] = DeliveryReceipt(
        request_id="expired",
        bot_id="bot",
        node_id="node",
        status="sent",
        updated_at=datetime.now(UTC) - timedelta(days=2),
    )

    for index in range(3):
        await manager.update_delivery_receipt(
            request_id=f"r{index}",
            bot_id="bot",
            node_id="node",
            status="sent",
        )

    assert "expired" not in manager._receipts
    assert len(manager._receipts) == 2
    assert "r0" not in manager._receipts
    assert {"r1", "r2"} == set(manager._receipts)


@pytest.mark.asyncio
async def test_sync_accounts_removes_binding_for_disappeared_account(tmp_path: Path):
    manager = WeChatDesktopManager(tmp_path / "nodes.json")
    code = await manager.create_pairing_code("warehouse")
    node_id, _token, _name = await manager.consume_pairing_code(code)
    await manager.sync_accounts(
        node_id,
        [
            {"id": "keep", "nickname": "Keep"},
            {"id": "gone", "nickname": "Gone"},
        ],
    )
    await manager.bind_account(node_id, "keep", "bot-keep", True)
    await manager.bind_account(node_id, "gone", "bot-gone", True)

    await manager.sync_accounts(node_id, [{"id": "keep", "nickname": "Keep"}])

    assert manager._bindings == {(node_id, "keep"): "bot-keep"}
    reloaded = WeChatDesktopManager(tmp_path / "nodes.json")
    assert reloaded._bindings == {(node_id, "keep"): "bot-keep"}
