from __future__ import annotations

import json
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.yaml"


def main() -> None:
    print("OpenAkita 微信（桌面版）Connector 配对")
    oa_url = input("OA 地址（例如 https://oa.example.com）: ").strip().rstrip("/")
    code = input("OA 页面生成的 8 位配对码: ").strip()
    response = requests.post(
        f"{oa_url}/api/wechat-desktop/pair",
        json={"code": code},
        timeout=30,
    )
    if response.status_code >= 400:
        raise SystemExit(f"配对失败: {response.status_code} {response.text}")
    data = response.json()
    config = {
        "oa_url": oa_url,
        "node_id": data["node_id"],
        "node_token": data["node_token"],
        "node_name": data.get("node_name", "Windows 微信节点"),
    }
    CONFIG_PATH.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), "utf-8")
    print("配对成功，配置已保存。现在运行 run.bat。")


if __name__ == "__main__":
    main()
