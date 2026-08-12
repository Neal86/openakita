#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch_capability_routing() -> None:
    path = ROOT / "src/openakita/hermes/capability_bridge.py"
    text = path.read_text("utf-8")

    context_marker = '''        "Use oa_* bridged functions for durable OpenAkita capabilities; descriptions contain original tool names.",\n'''
    routing_line = '''        "For Windows computer/app control, Agent-owned Windows Connector capabilities have priority over runtime-native computer-control tools. First call the bridged windows_list_apps and use the authorized oa_* Windows tools whenever matching local or remote resources exist. Use Hermes-native Computer Control only as a fallback when Windows Connector has no matching authorized resource or is unavailable. This routing rule is independent of whether the Agent runtime is Hermes or OpenAkita native.",\n'''
    if routing_line.strip() not in text:
        if context_marker not in text:
            raise RuntimeError("capability context marker missing")
        text = text.replace(context_marker, context_marker + routing_line, 1)

    marker = '''        proxy["description"] = (\n            f"[OpenAkita tool: {original}] " + str(schema.get("description") or "")\n        ).strip()\n'''
    replacement = '''        description_prefix = f"[OpenAkita tool: {original}] "\n        if original.startswith("windows_"):\n            description_prefix += "[Preferred Windows control path when an authorized Connector resource exists; use runtime-native computer control only as fallback.] "\n        proxy["description"] = (description_prefix + str(schema.get("description") or "")).strip()\n'''
    if replacement not in text:
        if marker not in text:
            raise RuntimeError("capability description marker missing")
        text = text.replace(marker, replacement, 1)

    path.write_text(text, "utf-8")


def verify_windows_device_ui() -> None:
    sidebar = (ROOT / "apps/setup-center/src/components/Sidebar.tsx").read_text("utf-8")
    execution = (ROOT / "apps/setup-center/src/views/ExecutionInstancesView.tsx").read_text("utf-8")
    im_config = (ROOT / "apps/setup-center/src/views/IMConfigView.tsx").read_text("utf-8")
    panel = (ROOT / "apps/setup-center/src/components/WindowsConnectorPanel.tsx").read_text("utf-8")

    required_sidebar = [
        'openExecutionPage("windows")',
        'title="Windows 设备"',
        '<span>Windows 设备</span>',
    ]
    for marker in required_sidebar:
        if marker not in sidebar:
            raise RuntimeError(f"Windows Devices sidebar marker missing: {marker}")
    if '<WindowsConnectorPanel apiBaseUrl={apiBaseUrl} />' not in execution:
        raise RuntimeError("ExecutionInstancesView does not render WindowsConnectorPanel")
    if "WechatDesktopPanel" in im_config:
        raise RuntimeError("remote Windows Connector UI is still mounted in IM configuration")
    for marker in ("本机", "远程设备", "生成配对码", "下载远程 Connector"):
        if marker not in panel:
            raise RuntimeError(f"WindowsConnectorPanel marker missing: {marker}")


def main() -> None:
    verify_windows_device_ui()
    patch_capability_routing()
    print("Final Windows device UI verified and Agent runtime routing patch applied")


if __name__ == "__main__":
    main()
