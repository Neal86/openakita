#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch_im_view() -> None:
    path = ROOT / "apps/setup-center/src/views/IMView.tsx"
    text = path.read_text("utf-8")
    import_marker = 'import { WechatQRModal } from "../components/WechatQRModal";\n'
    import_line = 'import { WechatDesktopNodes } from "../components/WechatDesktopNodes";\n'
    if import_line not in text:
        if import_marker not in text:
            raise RuntimeError("IMView import marker missing")
        text = text.replace(import_marker, import_marker + import_line, 1)

    old_state = 'const [activeTab, setActiveTab] = useState<"messages" | "groupPolicy">("messages");'
    new_state = 'const [activeTab, setActiveTab] = useState<"messages" | "groupPolicy" | "wechatDesktop">("messages");'
    if old_state in text:
        text = text.replace(old_state, new_state, 1)
    elif new_state not in text:
        raise RuntimeError("IMView activeTab marker missing")

    old_cast = 'setActiveTab(v as "messages" | "groupPolicy");'
    new_cast = 'setActiveTab(v as "messages" | "groupPolicy" | "wechatDesktop");'
    text = text.replace(old_cast, new_cast)

    group_item = '''            <ToggleGroupItem
              value="groupPolicy"
              className="text-sm px-4 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:border-primary"
            >
              {t("im.tabGroupPolicy")}
            </ToggleGroupItem>'''
    desktop_item = group_item + '''
            <ToggleGroupItem
              value="wechatDesktop"
              className="text-sm px-4 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:border-primary"
            >
              微信 Connector
            </ToggleGroupItem>'''
    if 'value="wechatDesktop"' not in text:
        if group_item not in text:
            raise RuntimeError("IMView tab marker missing")
        text = text.replace(group_item, desktop_item, 1)

    render_marker = '''        {activeTab === "messages" && <MessagesTab serviceRunning={serviceRunning} apiBase={api} />}
        {activeTab === "groupPolicy" && <GroupPolicyTab apiBase={api} />}'''
    render_replacement = render_marker + '''
        {activeTab === "wechatDesktop" && <WechatDesktopNodes apiBase={api} />}'''
    if '<WechatDesktopNodes apiBase={api}' not in text:
        if render_marker not in text:
            raise RuntimeError("IMView render marker missing")
        text = text.replace(render_marker, render_replacement, 1)
    path.write_text(text, "utf-8")


def patch_wechat_route() -> None:
    path = ROOT / "src/openakita/api/routes/wechat_desktop.py"
    text = path.read_text("utf-8")
    if "class PairingCloseRequest" not in text:
        marker = '''class PairingConsumeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=20)
'''
        replacement = marker + '''

class PairingCloseRequest(BaseModel):
    code: str = Field(min_length=6, max_length=20)
'''
        if marker not in text:
            raise RuntimeError("pairing request marker missing")
        text = text.replace(marker, replacement, 1)

    if '@router.post("/pairing-code/close")' not in text:
        marker = '''@router.post("/pair")
async def pair_connector(body: PairingConsumeRequest) -> dict[str, str]:
'''
        endpoint = '''@router.post("/pairing-code/close")
async def close_pairing_code(body: PairingCloseRequest) -> dict[str, bool]:
    digest = wechat_desktop_manager._hash(body.code.strip())
    async with wechat_desktop_manager._lock:
        ticket = wechat_desktop_manager._pairings.pop(digest, None)
    return {"ok": True, "closed": ticket is not None}


'''
        if marker not in text:
            raise RuntimeError("pair route marker missing")
        text = text.replace(marker, endpoint + marker, 1)
    path.write_text(text, "utf-8")


def main() -> None:
    patch_im_view()
    patch_wechat_route()
    print("WeChat Connector UI integration applied")


if __name__ == "__main__":
    main()
