from pathlib import Path


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text("utf-8")
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"{label} marker changed")
    path.write_text(text.replace(old, new, 1), "utf-8")


def main() -> None:
    connector = Path("src/openakita/wechat_desktop/connector_bundle/connector.py")
    replace_exact(
        connector,
        '''                ) as socket:\n                    logger.info("已连接 OpenAkita OA")\n                    accounts = await driver_call(driver.accounts)\n''',
        '''                ) as socket:\n                    logger.info("已连接 OpenAkita OA")\n                    # Each WebSocket attach receives the authoritative active Bot\n                    # configuration from OA. Drop stale configs from the previous\n                    # connection before applying that snapshot.\n                    bot_configs.clear()\n                    accounts = await driver_call(driver.accounts)\n''',
        "connector reconnect config reset",
    )
    replace_exact(
        connector,
        '''                            elif event == "config.sync":\n                                bot_configs[bot_id] = dict(payload)\n                                chats = set(\n                                    payload.get("allowed_groups") or []\n                                ) | set(payload.get("allowed_contacts") or [])\n                                await driver_call(driver.listen, sorted(chats))\n                                await socket.send(\n                                    json.dumps(\n                                        {\n                                            "event": "config.applied",\n                                            "bot_id": bot_id,\n                                            "payload": {"ok": True},\n                                        }\n                                    )\n                                )\n''',
        '''                            elif event == "config.sync":\n                                bot_configs[bot_id] = dict(payload)\n                                chats = set(\n                                    payload.get("allowed_groups") or []\n                                ) | set(payload.get("allowed_contacts") or [])\n                                await driver_call(driver.listen, sorted(chats))\n                                await socket.send(\n                                    json.dumps(\n                                        {\n                                            "event": "config.applied",\n                                            "bot_id": bot_id,\n                                            "payload": {"ok": True},\n                                        }\n                                    )\n                                )\n                            elif event == "config.remove":\n                                bot_configs.pop(bot_id, None)\n                                await socket.send(\n                                    json.dumps(\n                                        {\n                                            "event": "config.applied",\n                                            "bot_id": bot_id,\n                                            "payload": {"ok": True, "removed": True},\n                                        }\n                                    )\n                                )\n''',
        "connector config remove",
    )

    adapter = Path("src/openakita/channels/adapters/wechat_desktop.py")
    replace_exact(
        adapter,
        '''    async def stop(self) -> None:\n        self._running = False\n        for task in self._merge_tasks.values():\n            task.cancel()\n        self._merge_tasks.clear()\n        self._pending.clear()\n        await wechat_desktop_manager.unregister_bot_callback(self.bot_id)\n        await wechat_desktop_manager.bind_account(self.node_id, self.wechat_account_id, self.bot_id, False)\n''',
        '''    async def stop(self) -> None:\n        self._running = False\n        tasks = list(self._merge_tasks.values())\n        for task in tasks:\n            task.cancel()\n        if tasks:\n            await asyncio.gather(*tasks, return_exceptions=True)\n        self._merge_tasks.clear()\n        self._pending.clear()\n        self._last_send.clear()\n        self._send_locks.clear()\n        try:\n            await wechat_desktop_manager.send_command(\n                self.node_id,\n                {\n                    "version": 1,\n                    "event": "config.remove",\n                    "bot_id": self.bot_id,\n                    "payload": {},\n                },\n            )\n        except ConnectionError:\n            # Reconnect starts from an empty connector-side config snapshot, so\n            # an offline node cannot preserve this stale Bot indefinitely.\n            pass\n        await wechat_desktop_manager.unregister_bot_callback(self.bot_id)\n        await wechat_desktop_manager.bind_account(\n            self.node_id, self.wechat_account_id, self.bot_id, False\n        )\n''',
        "adapter stop cleanup",
    )

    test = Path("tests/wechat_desktop/test_bot_lifecycle_cleanup.py")
    test.write_text(
        '''import pytest\n\nfrom openakita.channels.adapters import wechat_desktop as adapter_module\nfrom openakita.channels.adapters.wechat_desktop import WeChatDesktopAdapter\n\n\n@pytest.mark.asyncio\nasync def test_stop_removes_connector_bot_config(monkeypatch):\n    sent = []\n    unregistered = []\n    bindings = []\n\n    async def send_command(node_id, command):\n        sent.append((node_id, command))\n\n    async def unregister(bot_id):\n        unregistered.append(bot_id)\n\n    async def bind(node_id, account_id, bot_id, enabled):\n        bindings.append((node_id, account_id, bot_id, enabled))\n\n    monkeypatch.setattr(adapter_module.wechat_desktop_manager, "send_command", send_command)\n    monkeypatch.setattr(adapter_module.wechat_desktop_manager, "unregister_bot_callback", unregister)\n    monkeypatch.setattr(adapter_module.wechat_desktop_manager, "bind_account", bind)\n\n    adapter = WeChatDesktopAdapter(\n        node_id="node-1",\n        wechat_account_id="account-1",\n        bot_id="bot-1",\n    )\n    adapter._running = True\n    await adapter.stop()\n\n    assert sent == [(\n        "node-1",\n        {"version": 1, "event": "config.remove", "bot_id": "bot-1", "payload": {}},\n    )]\n    assert unregistered == ["bot-1"]\n    assert bindings == [("node-1", "account-1", "bot-1", False)]\n\n\n@pytest.mark.asyncio\nasync def test_stop_clears_long_lived_send_state(monkeypatch):\n    async def offline(*_args, **_kwargs):\n        raise ConnectionError("offline")\n\n    async def noop(*_args, **_kwargs):\n        return None\n\n    monkeypatch.setattr(adapter_module.wechat_desktop_manager, "send_command", offline)\n    monkeypatch.setattr(adapter_module.wechat_desktop_manager, "unregister_bot_callback", noop)\n    monkeypatch.setattr(adapter_module.wechat_desktop_manager, "bind_account", noop)\n\n    adapter = WeChatDesktopAdapter(node_id="node-1", wechat_account_id="account-1")\n    adapter._last_send["chat"] = 1.0\n    adapter._send_locks["chat"] = __import__("asyncio").Lock()\n    await adapter.stop()\n    assert adapter._last_send == {}\n    assert adapter._send_locks == {}\n''',
        "utf-8",
    )


if __name__ == "__main__":
    main()
