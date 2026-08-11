#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    workflow = ROOT / ".github/workflows/wechat-connector-release.yml"
    text = workflow.read_text("utf-8")
    text = text.replace("name: WeChat Connector Windows release", "name: Windows Connector release")
    text = text.replace("OpenAkita-WeChat-Connector-Windows-x64", "OpenAkita-Windows-Connector-Windows-x64")
    text = text.replace("OpenAkita-WeChat-Connector.exe", "OpenAkita-Windows-Connector.exe")
    text = text.replace("OpenAkita-WeChat-Connector-Worker.exe", "OpenAkita-Windows-Connector-Worker.exe")
    text = text.replace("Publish stable Connector download", "Publish stable Windows Connector download")
    text = text.replace("OpenAkita WeChat Connector Windows x64", "OpenAkita Windows Connector x64")
    text = text.replace("RELEASE_TAG: wechat-connector-latest", "RELEASE_TAG: windows-connector-latest")
    text = text.replace('"workflow": "WeChat Connector Windows release"', '"workflow": "Windows Connector release"')
    additions = [
        '      - "src/openakita/windows_connector/**"\n',
        '      - "src/openakita/api/routes/windows_connector.py"\n',
        '      - "apps/setup-center/src/components/WindowsConnectorPanel.tsx"\n',
        '      - "tests/windows_connector/**"\n',
    ]
    marker = '      - "src/openakita/wechat_desktop/**"\n'
    for addition in additions:
        if addition not in text:
            # Add to both push and pull_request path lists.
            text = text.replace(marker, marker + addition)
    workflow.write_text(text, "utf-8")

    # New generic download route points at its own stable release tag.
    route = ROOT / "src/openakita/api/routes/windows_connector.py"
    text = route.read_text("utf-8").replace(
        "f\"wechat-connector-latest/{RELEASE_FILENAME}\"",
        "f\"windows-connector-latest/{RELEASE_FILENAME}\"",
    )
    route.write_text(text, "utf-8")

    # Packaged connector tests now expect the generic sibling Worker filename.
    test = ROOT / "tests/wechat_desktop/test_connector_desktop_ui.py"
    text = test.read_text("utf-8")
    text = text.replace("OpenAkita-WeChat-Connector.exe", "OpenAkita-Windows-Connector.exe")
    text = text.replace("OpenAkita-WeChat-Connector-Worker.exe", "OpenAkita-Windows-Connector-Worker.exe")
    test.write_text(text, "utf-8")

    print("Windows Connector CI integration applied")


if __name__ == "__main__":
    main()
