from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "wechat-connector"
RELEASE = ROOT / "dist" / "OpenAkita-Windows-Connector-Windows-x64"


def run(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "PyInstaller", *args], cwd=ROOT, check=True)


def main() -> None:
    shutil.rmtree(DIST, ignore_errors=True)
    shutil.rmtree(RELEASE, ignore_errors=True)
    DIST.mkdir(parents=True, exist_ok=True)
    hidden = [
        "--hidden-import=wxauto4",
        "--hidden-import=websockets",
        "--hidden-import=yaml",
        "--collect-all=wxauto4",
        "--hidden-import=psutil",
        "--hidden-import=pywinauto",
        "--hidden-import=PIL",
        "--hidden-import=pyperclip",
        "--collect-submodules=pywinauto",
    ]
    run(
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name=OpenAkita-Windows-Connector",
        f"--distpath={DIST}",
        f"--workpath={ROOT / 'build' / 'wechat-ui-work'}",
        f"--specpath={ROOT / 'build'}",
        *hidden,
        str(ROOT / "build" / "wechat_connector_entry.py"),
    )
    run(
        "--noconfirm", "--clean", "--onefile", "--console",
        "--name=OpenAkita-Windows-Connector-Worker",
        f"--distpath={DIST}",
        f"--workpath={ROOT / 'build' / 'wechat-worker-work'}",
        f"--specpath={ROOT / 'build'}",
        *hidden,
        str(ROOT / "build" / "wechat_connector_worker_entry.py"),
    )
    RELEASE.mkdir(parents=True, exist_ok=True)
    for name in ("OpenAkita-Windows-Connector.exe", "OpenAkita-Windows-Connector-Worker.exe"):
        shutil.copy2(DIST / name, RELEASE / name)
    (RELEASE / "README.txt").write_text(
        "OpenAkita Windows Connector\n\n"
        "1. 保持需要授权给 Agent 的本机应用已运行；微信功能需要微信电脑版已登录。\n"
        "2. 双击 OpenAkita-WeChat-Connector.exe。\n"
        "3. 输入 OpenAkita 地址和网页生成的 8 位配对码。\n"
        "4. 点击配对，再点击启动；Connector 会自动扫描运行应用、微信实例和浏览器 Tab。\n\n"
        "配置和日志保存在 %APPDATA%\\OpenAkita\\WeChatConnector。\n",
        "utf-8",
    )
    archive = ROOT / "dist" / "OpenAkita-Windows-Connector-Windows-x64.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in RELEASE.rglob("*"):
            if path.is_file():
                zf.write(path, Path(RELEASE.name) / path.relative_to(RELEASE))
    print(archive)


if __name__ == "__main__":
    main()
