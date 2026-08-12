#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text("utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"marker missing in {path}: {old[:160]!r}")
    target.write_text(text.replace(old, new, 1), "utf-8")


def patch_types() -> None:
    path = ROOT / "apps/setup-center/src/types.ts"
    text = path.read_text("utf-8")
    old = '"agent_manager" | "execution_instances" | "agent_store"'
    new = '"agent_manager" | "execution_instances" | "windows_devices" | "agent_store"'
    if new not in text:
        if old not in text:
            raise RuntimeError("ViewId marker missing")
        text = text.replace(old, new, 1)
    path.write_text(text, "utf-8")


def patch_app() -> None:
    path = ROOT / "apps/setup-center/src/App.tsx"
    text = path.read_text("utf-8")

    lazy_marker = 'const ExecutionInstancesView = lazy(() => import("./views/ExecutionInstancesView").then(m => ({ default: m.ExecutionInstancesView })));\n'
    lazy_add = lazy_marker + 'const WindowsDevicesView = lazy(() => import("./components/WindowsConnectorPanel").then(m => ({ default: m.WindowsConnectorPanel })));\n'
    if 'const WindowsDevicesView = lazy(' not in text:
        if lazy_marker not in text:
            raise RuntimeError("App lazy marker missing")
        text = text.replace(lazy_marker, lazy_add, 1)

    hash_marker = '  "agent-manager": "agent_manager", "execution-instances": "execution_instances", "agent-store": "agent_store",\n'
    hash_add = '  "agent-manager": "agent_manager", "execution-instances": "execution_instances", "windows-devices": "windows_devices", "agent-store": "agent_store",\n'
    if '"windows-devices": "windows_devices"' not in text:
        if hash_marker not in text:
            raise RuntimeError("App hash marker missing")
        text = text.replace(hash_marker, hash_add, 1)

    render_marker = '''    if (view === "execution_instances") {\n      return <ExecutionInstancesView apiBaseUrl={apiBaseUrl} />;\n    }\n'''
    render_add = render_marker + '''    if (view === "windows_devices") {\n      return <WindowsDevicesView apiBaseUrl={apiBaseUrl || DEFAULT_LOCAL_API_BASE} />;\n    }\n'''
    if 'view === "windows_devices"' not in text:
        if render_marker not in text:
            raise RuntimeError("App render marker missing")
        text = text.replace(render_marker, render_add, 1)

    path.write_text(text, "utf-8")


def patch_sidebar() -> None:
    path = ROOT / "apps/setup-center/src/components/Sidebar.tsx"
    text = path.read_text("utf-8")
    old_group = 'const maViews: ViewId[] = ["dashboard", "org_editor", "pixel_office", "agent_manager", "execution_instances"];'
    new_group = 'const maViews: ViewId[] = ["dashboard", "org_editor", "pixel_office", "agent_manager", "execution_instances", "windows_devices"];'
    if new_group not in text:
        if old_group not in text:
            raise RuntimeError("Sidebar maViews marker missing")
        text = text.replace(old_group, new_group, 1)

    marker = '''            <div className={`navItem ${view === "execution_instances" ? "navItemActive" : ""}`} onClick={() => onViewChange("execution_instances")} role="button" tabIndex={0} title="执行模式实例">\n              <IconGear size={16} /> {!collapsed && <span>执行模式实例</span>}\n            </div>\n'''
    add = marker + '''            <div className={`navItem ${view === "windows_devices" ? "navItemActive" : ""}`} onClick={() => onViewChange("windows_devices")} role="button" tabIndex={0} title="Windows 设备">\n              <IconPlug size={16} /> {!collapsed && <span>Windows 设备</span>}\n            </div>\n'''
    if 'view === "windows_devices"' not in text:
        if marker not in text:
            raise RuntimeError("Sidebar execution instance marker missing")
        text = text.replace(marker, add, 1)
    path.write_text(text, "utf-8")


def patch_capability_routing() -> None:
    path = ROOT / "src/openakita/hermes/capability_bridge.py"
    text = path.read_text("utf-8")

    context_marker = '''        "Use oa_* bridged functions for durable OpenAkita capabilities; descriptions contain original tool names.",\n'''
    routing_line = '''        "For Windows computer/app control, Agent-owned Windows Connector capabilities have priority over runtime-native computer-control tools. First call the bridged windows_list_apps and use the authorized oa_* Windows tools whenever matching local or remote resources exist. Use Hermes-native Computer Control only as a fallback when Windows Connector has no matching authorized resource or is unavailable. This routing rule is independent of whether the Agent runtime is Hermes or OpenAkita native.",\n'''
    if routing_line.strip() not in text:
        if context_marker not in text:
            raise RuntimeError("capability context marker missing")
        text = text.replace(context_marker, context_marker + routing_line, 1)

    # Make the preference visible directly in each bridged Windows tool description,
    # not only in system context. This strongly biases Hermes' tool selection while
    # preserving its native fallback tools for unsupported/unavailable resources.
    marker = '''        proxy["description"] = (\n            f"[OpenAkita tool: {original}] " + str(schema.get("description") or "")\n        ).strip()\n'''
    replacement = '''        description_prefix = f"[OpenAkita tool: {original}] "\n        if original.startswith("windows_"):\n            description_prefix += "[Preferred Windows control path when an authorized Connector resource exists; use runtime-native computer control only as fallback.] "\n        proxy["description"] = (description_prefix + str(schema.get("description") or "")).strip()\n'''
    if replacement not in text:
        if marker not in text:
            raise RuntimeError("capability description marker missing")
        text = text.replace(marker, replacement, 1)

    path.write_text(text, "utf-8")


def main() -> None:
    patch_types()
    patch_app()
    patch_sidebar()
    patch_capability_routing()
    print("Final Windows device UI + Agent runtime routing patch applied")


if __name__ == "__main__":
    main()
