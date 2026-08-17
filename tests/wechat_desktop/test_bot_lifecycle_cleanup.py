import pytest

from openakita.channels.adapters import wechat_desktop as adapter_module
from openakita.channels.adapters.wechat_desktop import WeChatDesktopAdapter


@pytest.mark.asyncio
async def test_stop_removes_connector_bot_config(monkeypatch):
    sent = []
    unregistered = []
    bindings = []

    async def send_command(node_id, command):
        sent.append((node_id, command))

    async def unregister(bot_id):
        unregistered.append(bot_id)

    async def bind(node_id, account_id, bot_id, enabled):
        bindings.append((node_id, account_id, bot_id, enabled))

    monkeypatch.setattr(adapter_module.wechat_desktop_manager, "send_command", send_command)
    monkeypatch.setattr(adapter_module.wechat_desktop_manager, "unregister_bot_callback", unregister)
    monkeypatch.setattr(adapter_module.wechat_desktop_manager, "bind_account", bind)

    adapter = WeChatDesktopAdapter(
        node_id="node-1",
        wechat_account_id="account-1",
        bot_id="bot-1",
    )
    adapter._running = True
    await adapter.stop()

    assert sent == [(
        "node-1",
        {"version": 1, "event": "config.remove", "bot_id": "bot-1", "payload": {}},
    )]
    assert unregistered == ["bot-1"]
    assert bindings == [("node-1", "account-1", "bot-1", False)]


@pytest.mark.asyncio
async def test_stop_clears_long_lived_send_state(monkeypatch):
    async def offline(*_args, **_kwargs):
        raise ConnectionError("offline")

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(adapter_module.wechat_desktop_manager, "send_command", offline)
    monkeypatch.setattr(adapter_module.wechat_desktop_manager, "unregister_bot_callback", noop)
    monkeypatch.setattr(adapter_module.wechat_desktop_manager, "bind_account", noop)

    adapter = WeChatDesktopAdapter(node_id="node-1", wechat_account_id="account-1")
    adapter._last_send["chat"] = 1.0
    adapter._send_locks["chat"] = __import__("asyncio").Lock()
    await adapter.stop()
    assert adapter._last_send == {}
    assert adapter._send_locks == {}
