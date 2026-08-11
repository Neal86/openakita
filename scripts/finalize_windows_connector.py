#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text("utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"marker missing in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), "utf-8")


def fix_frontend_api() -> None:
    path = ROOT / "apps/setup-center/src/components/WindowsConnectorPanel.tsx"
    text = path.read_text("utf-8")
    old_sig = '''function ResourceCard({\n  node,\n  resource,\n  profiles,\n  reload,\n}: {\n  node: NodeInfo;\n  resource: Resource;\n  profiles: AgentProfile[];\n  reload: () => Promise<void>;\n}) {'''
    new_sig = '''function ResourceCard({\n  api,\n  node,\n  resource,\n  profiles,\n  reload,\n}: {\n  api: string;\n  node: NodeInfo;\n  resource: Resource;\n  profiles: AgentProfile[];\n  reload: () => Promise<void>;\n}) {'''
    if new_sig not in text:
        if old_sig not in text:
            raise RuntimeError("ResourceCard signature marker missing")
        text = text.replace(old_sig, new_sig, 1)
    text = text.replace("`${DEFAULT_API}/api/windows-connector/grants`", "`${api}/api/windows-connector/grants`")
    text = text.replace("`${DEFAULT_API}/api/windows-connector/grants/${encodeURIComponent(grantId)}`", "`${api}/api/windows-connector/grants/${encodeURIComponent(grantId)}`")
    old_render = '<ResourceCard key={resource.id} node={node} resource={resource} profiles={profiles} reload={load} />'
    new_render = '<ResourceCard key={resource.id} api={api} node={node} resource={resource} profiles={profiles} reload={load} />'
    text = text.replace(old_render, new_render)
    path.write_text(text, "utf-8")


def add_launch_tool() -> None:
    path = ROOT / "src/openakita/windows_connector/tools.py"
    text = path.read_text("utf-8")
    if '"name": "windows_launch_app"' not in text:
        marker = '''    {\n        "name": "windows_close_app",\n        "category": "Windows Connector",\n'''
        block = '''    {\n        "name": "windows_launch_app",\n        "category": "Windows Connector",\n        "description": "Launch another instance of an authorized Windows application using the exact executable path discovered for that grant. Requires launch permission.",\n        "input_schema": {"type": "object", "properties": _base_properties(), "required": ["node_id", "resource_id"]},\n    },\n'''
        if marker not in text:
            raise RuntimeError("windows_close_app marker missing")
        text = text.replace(marker, block + marker, 1)
    if '"windows_launch_app": "launch"' not in text:
        text = text.replace('    "windows_browser_type": "browser_type",\n', '    "windows_browser_type": "browser_type",\n    "windows_launch_app": "launch",\n', 1)
    if '"windows_launch_app": ApprovalClass.EXEC_CAPABLE' not in text:
        text = text.replace('        "windows_browser_type": ApprovalClass.EXEC_CAPABLE,\n', '        "windows_browser_type": ApprovalClass.EXEC_CAPABLE,\n        "windows_launch_app": ApprovalClass.EXEC_CAPABLE,\n', 1)
    path.write_text(text, "utf-8")


def add_generic_pairing_aliases() -> None:
    path = ROOT / "src/openakita/api/routes/windows_connector.py"
    text = path.read_text("utf-8")
    if "class PairingCreatePayload" not in text:
        marker = "\n\nclass GrantPayload(BaseModel):\n"
        models = '''\n\nclass PairingCreatePayload(BaseModel):\n    node_name: str = Field(default="Windows 电脑", min_length=1, max_length=100)\n    ttl_seconds: int = Field(default=3600, ge=60, le=3600)\n\n\nclass PairingConsumePayload(BaseModel):\n    code: str = Field(min_length=6, max_length=20)\n\n\nclass PairingClosePayload(BaseModel):\n    code: str = Field(min_length=6, max_length=20)\n'''
        if marker not in text:
            raise RuntimeError("GrantPayload marker missing")
        text = text.replace(marker, models + marker, 1)
    if '@router.post("/pairing-code")' not in text:
        marker = '\n\n@router.get("/nodes")\n'
        routes = '''\n\n@router.post("/pairing-code")\nasync def create_pairing_code(body: PairingCreatePayload) -> dict[str, Any]:\n    code = await wechat_desktop_manager.create_pairing_code(body.node_name, body.ttl_seconds)\n    return {"code": code, "expires_in": body.ttl_seconds}\n\n\n@router.post("/pairing-code/close")\nasync def close_pairing_code(body: PairingClosePayload) -> dict[str, bool]:\n    return {"ok": True, "closed": await wechat_desktop_manager.cancel_pairing_code(body.code)}\n\n\n@router.post("/pair")\nasync def pair_connector(body: PairingConsumePayload) -> dict[str, str]:\n    try:\n        node_id, node_token, node_name = await wechat_desktop_manager.consume_pairing_code(body.code)\n    except ValueError as exc:\n        raise HTTPException(status_code=400, detail="配对码无效或已过期") from exc\n    return {"node_id": node_id, "node_token": node_token, "node_name": node_name}\n'''
        if marker not in text:
            raise RuntimeError("nodes route marker missing")
        text = text.replace(marker, routes + marker, 1)
    path.write_text(text, "utf-8")


def point_connector_at_generic_pair_api() -> None:
    path = ROOT / "src/openakita/wechat_desktop/connector_bundle/app.py"
    text = path.read_text("utf-8")
    text = text.replace('requests.post(f"{url}/api/wechat-desktop/pair",', 'requests.post(f"{url}/api/windows-connector/pair",')
    path.write_text(text, "utf-8")


def main() -> None:
    fix_frontend_api()
    add_launch_tool()
    add_generic_pairing_aliases()
    point_connector_at_generic_pair_api()
    print("Windows Connector finalization applied")


if __name__ == "__main__":
    main()
