#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text("utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"marker missing in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), "utf-8")


def patch_server() -> None:
    patch(
        "src/openakita/api/server.py",
        "    wechat_onboard,\n    wecom_onboard,\n",
        "    wechat_onboard,\n    windows_connector,\n    wecom_onboard,\n",
    )
    patch(
        "src/openakita/api/server.py",
        '    app.include_router(wechat_onboard.router, tags=["微信扫码"])\n    app.include_router(wecom_onboard.router, tags=["企微扫码"])\n',
        '    app.include_router(wechat_onboard.router, tags=["微信扫码"])\n    app.include_router(windows_connector.router, tags=["Windows Connector"])\n    app.include_router(wecom_onboard.router, tags=["企微扫码"])\n',
    )


def patch_wechat_ws() -> None:
    patch(
        "src/openakita/api/routes/wechat_desktop.py",
        "from openakita.wechat_desktop import wechat_desktop_manager\n",
        "from openakita.wechat_desktop import wechat_desktop_manager\nfrom openakita.windows_connector import windows_connector_manager\n",
    )
    patch(
        "src/openakita/api/routes/wechat_desktop.py",
        "    for command in _configured_bots_for_node(node_id):\n        await websocket.send_json(command)\n\n    try:\n",
        "    for command in _configured_bots_for_node(node_id):\n        await websocket.send_json(command)\n    for command in await windows_connector_manager.commands_for_attach(node_id):\n        await websocket.send_json(command)\n\n    try:\n",
    )
    patch(
        "src/openakita/api/routes/wechat_desktop.py",
        "            if event == \"node.heartbeat\":\n                await wechat_desktop_manager.heartbeat(node_id)\n            elif event == \"wechat.accounts.sync\":\n",
        "            if event == \"node.heartbeat\":\n                await wechat_desktop_manager.heartbeat(node_id)\n            elif event == \"windows.resources.sync\":\n                await windows_connector_manager.sync_resources(node_id, payload.get(\"resources\") or [])\n            elif event == \"windows.command.result\":\n                request_id = str(envelope.get(\"request_id\") or payload.get(\"request_id\") or \"\")\n                if request_id:\n                    await windows_connector_manager.handle_result(request_id, payload)\n            elif event == \"wechat.accounts.sync\":\n",
    )


def patch_connector_runtime() -> None:
    patch(
        "src/openakita/wechat_desktop/connector_bundle/connector.py",
        "from wxauto4 import WeChat\n",
        "from wxauto4 import WeChat\n\nfrom openakita.windows_connector.executor import WindowsCommandExecutor\n",
    )
    patch(
        "src/openakita/wechat_desktop/connector_bundle/connector.py",
        "    driver = DesktopDriver()\n    url = ws_url(str(config[\"oa_url\"]), str(config[\"node_id\"]), str(config[\"node_token\"]))\n",
        "    driver = DesktopDriver()\n    computer = WindowsCommandExecutor()\n    url = ws_url(str(config[\"oa_url\"]), str(config[\"node_id\"]), str(config[\"node_token\"]))\n",
    )
    patch(
        "src/openakita/wechat_desktop/connector_bundle/connector.py",
        "                    await socket.send(json.dumps({\"event\": \"wechat.conversations.sync\", \"payload\": {\"wechat_account_id\": accounts[0][\"id\"], \"groups\": groups, \"contacts\": contacts}}, ensure_ascii=False))\n\n                    async def heartbeat() -> None:\n",
        "                    await socket.send(json.dumps({\"event\": \"wechat.conversations.sync\", \"payload\": {\"wechat_account_id\": accounts[0][\"id\"], \"groups\": groups, \"contacts\": contacts}}, ensure_ascii=False))\n                    await socket.send(json.dumps({\"event\": \"windows.resources.sync\", \"payload\": {\"resources\": computer.resources()}}, ensure_ascii=False))\n\n                    async def heartbeat() -> None:\n",
    )
    patch(
        "src/openakita/wechat_desktop/connector_bundle/connector.py",
        "                    async def poll() -> None:\n                        while True:\n                            await asyncio.sleep(0.5)\n                            for payload in driver.poll_messages():\n",
        "                    async def resource_poll() -> None:\n                        previous = \"\"\n                        while True:\n                            await asyncio.sleep(8)\n                            resources = computer.resources()\n                            signature = json.dumps(resources, ensure_ascii=False, sort_keys=True)\n                            if signature != previous:\n                                previous = signature\n                                await socket.send(json.dumps({\"event\": \"windows.resources.sync\", \"payload\": {\"resources\": resources}}, ensure_ascii=False))\n\n                    async def poll() -> None:\n                        while True:\n                            await asyncio.sleep(0.5)\n                            for payload in driver.poll_messages():\n",
    )
    patch(
        "src/openakita/wechat_desktop/connector_bundle/connector.py",
        "                    heartbeat_task = asyncio.create_task(heartbeat())\n                    poll_task = asyncio.create_task(poll())\n                    try:\n",
        "                    heartbeat_task = asyncio.create_task(heartbeat())\n                    resource_task = asyncio.create_task(resource_poll())\n                    poll_task = asyncio.create_task(poll())\n                    try:\n",
    )
    patch(
        "src/openakita/wechat_desktop/connector_bundle/connector.py",
        "                            if event == \"config.sync\":\n                                bot_configs[bot_id] = dict(payload)\n",
        "                            if event == \"windows.permissions.sync\":\n                                computer.sync_grants(payload.get(\"grants\") or [])\n                            elif event == \"windows.resources.refresh\":\n                                await socket.send(json.dumps({\"event\": \"windows.resources.sync\", \"payload\": {\"resources\": computer.resources()}}, ensure_ascii=False))\n                            elif event == \"windows.command\":\n                                request_id = str(envelope.get(\"request_id\") or \"\")\n                                try:\n                                    result = await computer.execute(dict(payload))\n                                except Exception as exc:\n                                    result = {\"ok\": False, \"error\": str(exc), \"error_type\": type(exc).__name__}\n                                await socket.send(json.dumps({\"event\": \"windows.command.result\", \"request_id\": request_id, \"payload\": result}, ensure_ascii=False))\n                            elif event == \"config.sync\":\n                                bot_configs[bot_id] = dict(payload)\n",
    )
    patch(
        "src/openakita/wechat_desktop/connector_bundle/connector.py",
        "                    finally:\n                        heartbeat_task.cancel()\n                        poll_task.cancel()\n",
        "                    finally:\n                        heartbeat_task.cancel()\n                        resource_task.cancel()\n                        poll_task.cancel()\n",
    )


def patch_tool_executor() -> None:
    patch(
        "src/openakita/core/_tool_executor_legacy.py",
        "                if self._handler_registry.has_tool(tool_name):\n                    result = await self._handler_registry.execute_by_tool(tool_name, tool_input)\n                else:\n",
        "                if self._handler_registry.has_tool(tool_name):\n                    # Bind executor-owned Agent identity for local/Native Windows Connector tools.\n                    # If Hermes already bound an explicit profile, keep that stronger context.\n                    from ..windows_connector.context import current_agent_profile_id\n                    existing_profile = current_agent_profile_id.get(\"\")\n                    profile_token = None\n                    if not existing_profile:\n                        agent_ref = getattr(self, \"_agent_ref\", None)\n                        derived_profile = (\n                            getattr(agent_ref, \"_agent_profile_id\", \"\")\n                            or getattr(agent_ref, \"profile_id\", \"\")\n                            or getattr(getattr(agent_ref, \"profile\", None), \"id\", \"\")\n                        )\n                        if derived_profile:\n                            profile_token = current_agent_profile_id.set(str(derived_profile))\n                    try:\n                        result = await self._handler_registry.execute_by_tool(tool_name, tool_input)\n                    finally:\n                        if profile_token is not None:\n                            current_agent_profile_id.reset(profile_token)\n                else:\n",
    )


def patch_capability_bridge() -> None:
    path = ROOT / "src/openakita/hermes/capability_bridge.py"
    text = path.read_text("utf-8")
    marker = "    for raw in explicit_tools or []:\n"
    if "WINDOWS_CONNECTOR_TOOLS" not in text:
        addition = '''    # Windows Connector tools are global capabilities; per-Agent app grants are\n    # enforced again by the handler/connector and do not create private tool copies.\n    try:\n        from openakita.windows_connector.tools import WINDOWS_CONNECTOR_TOOLS\n    except Exception:\n        WINDOWS_CONNECTOR_TOOLS = []\n    for raw in WINDOWS_CONNECTOR_TOOLS:\n        normalized = _to_hermes_schema(raw)\n        if not normalized:\n            continue\n        original = str(normalized["name"])\n        if _tool_allowed(profile, tool_name=original, category="Windows Connector"):\n            original_schemas[original] = normalized\n\n'''
        if marker not in text:
            raise RuntimeError("capability bridge explicit tools marker missing")
        text = text.replace(marker, addition + marker, 1)
    old = '''    if agent is not None and getattr(agent, "tool_executor", None) is not None:\n        result, _hint = await agent.tool_executor.execute_tool(tool_name, args, session_id=session_id or None)\n    else:\n        from openakita.tools.handlers import default_handler_registry\n\n        result = await default_handler_registry.execute_by_tool(tool_name, args)\n'''
    new = '''    from openakita.windows_connector.context import current_agent_profile_id\n    profile_token = current_agent_profile_id.set(profile_id)\n    try:\n        if agent is not None and getattr(agent, "tool_executor", None) is not None:\n            result, _hint = await agent.tool_executor.execute_tool(tool_name, args, session_id=session_id or None)\n        else:\n            from openakita.tools.handlers import default_handler_registry\n\n            result = await default_handler_registry.execute_by_tool(tool_name, args)\n    finally:\n        current_agent_profile_id.reset(profile_token)\n'''
    if new not in text:
        if old not in text:
            raise RuntimeError("capability bridge execute marker missing")
        text = text.replace(old, new, 1)
    path.write_text(text, "utf-8")


def patch_frontend() -> None:
    path = ROOT / "apps/setup-center/src/views/IMView.tsx"
    text = path.read_text("utf-8")
    if 'WindowsConnectorPanel' not in text:
        marker = 'import { AgentIcon } from "../components/AgentIcon";\n'
        if marker not in text:
            raise RuntimeError("IMView import marker missing")
        text = text.replace(marker, marker + 'import { WindowsConnectorPanel } from "../components/WindowsConnectorPanel";\n', 1)
    text = text.replace('useState<"messages" | "groupPolicy">("messages")', 'useState<"messages" | "groupPolicy" | "windowsApps">("messages")')
    text = text.replace('v as "messages" | "groupPolicy"', 'v as "messages" | "groupPolicy" | "windowsApps"')
    if 'value="windowsApps"' not in text:
        marker = '''            <ToggleGroupItem\n              value="groupPolicy"\n              className="text-sm px-4 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:border-primary"\n            >\n              {t("im.tabGroupPolicy")}\n            </ToggleGroupItem>\n'''
        addition = marker + '''            <ToggleGroupItem\n              value="windowsApps"\n              className="text-sm px-4 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:border-primary"\n            >\n              本机应用\n            </ToggleGroupItem>\n'''
        if marker not in text:
            raise RuntimeError("IMView groupPolicy tab marker missing")
        text = text.replace(marker, addition, 1)
    if '<WindowsConnectorPanel' not in text:
        marker = '        {activeTab === "groupPolicy" && <GroupPolicyTab apiBase={api} />}\n'
        if marker not in text:
            raise RuntimeError("IMView card render marker missing")
        text = text.replace(marker, marker + '        {activeTab === "windowsApps" && <WindowsConnectorPanel apiBaseUrl={api} />}\n', 1)
    path.write_text(text, "utf-8")


def patch_connector_ui_and_build() -> None:
    # Existing pairing UI becomes the generic Windows Connector UI. The old
    # WeChat websocket/protocol remains as a backward-compatible transport.
    path = ROOT / "src/openakita/wechat_desktop/connector_bundle/app.py"
    text = path.read_text("utf-8")
    text = text.replace('self.title("OpenAkita 微信 Connector")', 'self.title("OpenAkita Windows Connector")')
    text = text.replace('ttk.Label(root, text="OpenAkita 微信 Connector"', 'ttk.Label(root, text="OpenAkita Windows Connector"')
    text = text.replace('ttk.Label(root, text="连接 Windows 微信电脑版与 OpenAkita"', 'ttk.Label(root, text="连接本机应用、浏览器、微信与 OpenAkita"')
    path.write_text(text, "utf-8")

    path = ROOT / "src/openakita/wechat_desktop/connector_bundle/connector_service.py"
    text = path.read_text("utf-8")
    old = '            worker = executable_dir / "OpenAkita-WeChat-Connector-Worker.exe"\n            return [str(worker)], executable_dir\n'
    new = '            worker = executable_dir / "OpenAkita-Windows-Connector-Worker.exe"\n            if not worker.exists():\n                worker = executable_dir / "OpenAkita-WeChat-Connector-Worker.exe"\n            return [str(worker)], executable_dir\n'
    if new not in text:
        if old not in text:
            raise RuntimeError("connector service worker marker missing")
        text = text.replace(old, new, 1)
    path.write_text(text, "utf-8")

    path = ROOT / "scripts/build_wechat_connector.py"
    text = path.read_text("utf-8")
    text = text.replace('RELEASE = ROOT / "dist" / "OpenAkita-WeChat-Connector-Windows-x64"', 'RELEASE = ROOT / "dist" / "OpenAkita-Windows-Connector-Windows-x64"')
    text = text.replace('"--name=OpenAkita-WeChat-Connector",', '"--name=OpenAkita-Windows-Connector",')
    text = text.replace('"--name=OpenAkita-WeChat-Connector-Worker",', '"--name=OpenAkita-Windows-Connector-Worker",')
    text = text.replace('for name in ("OpenAkita-WeChat-Connector.exe", "OpenAkita-WeChat-Connector-Worker.exe"):', 'for name in ("OpenAkita-Windows-Connector.exe", "OpenAkita-Windows-Connector-Worker.exe"):')
    text = text.replace('"OpenAkita 微信 Connector\\n\\n"', '"OpenAkita Windows Connector\\n\\n"')
    text = text.replace('"1. 保持 Windows 微信电脑版已登录。\\n"', '"1. 保持需要授权给 Agent 的本机应用已运行；微信功能需要微信电脑版已登录。\\n"')
    text = text.replace('"4. 点击配对，再点击启动。\\n\\n"', '"4. 点击配对，再点击启动；Connector 会自动扫描运行应用、微信实例和浏览器 Tab。\\n\\n"')
    text = text.replace('archive = ROOT / "dist" / "OpenAkita-WeChat-Connector-Windows-x64.zip"', 'archive = ROOT / "dist" / "OpenAkita-Windows-Connector-Windows-x64.zip"')
    hidden_marker = '        "--collect-all=wxauto4",\n'
    hidden_add = hidden_marker + '        "--hidden-import=psutil",\n        "--hidden-import=pywinauto",\n        "--hidden-import=PIL",\n        "--hidden-import=pyperclip",\n        "--collect-submodules=pywinauto",\n'
    if '"--hidden-import=psutil"' not in text:
        if hidden_marker not in text:
            raise RuntimeError("build hidden import marker missing")
        text = text.replace(hidden_marker, hidden_add, 1)
    path.write_text(text, "utf-8")


def main() -> None:
    patch_server()
    patch_wechat_ws()
    patch_connector_runtime()
    patch_tool_executor()
    patch_capability_bridge()
    patch_frontend()
    patch_connector_ui_and_build()
    print("Windows Connector integration applied")


if __name__ == "__main__":
    main()
