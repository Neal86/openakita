from __future__ import annotations

import os
from pathlib import Path

from openakita.wechat_desktop.connector_bundle import config_service
from openakita.wechat_desktop.connector_bundle.config_service import masked_token
from openakita.wechat_desktop.connector_bundle.connector_service import ConnectorService


def test_masked_token_never_exposes_full_secret() -> None:
    token = "super-secret-node-token"
    masked = masked_token(token)
    assert token not in masked
    assert masked.startswith("supe")
    assert masked.endswith("oken")


def test_config_roundtrip_uses_app_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config_service, "APP_DIR", tmp_path)
    monkeypatch.setattr(config_service, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_service, "LOG_PATH", tmp_path / "connector.log")
    payload = {"oa_url": "https://oa.example.com", "node_id": "node-1", "node_token": "secret"}
    config_service.save_config(payload)
    assert config_service.load_config() == payload
    config_service.clear_config()
    assert config_service.load_config() == {}


def test_service_uses_worker_script_when_not_frozen(monkeypatch) -> None:
    monkeypatch.delattr("sys.frozen", raising=False)
    command, cwd = ConnectorService._command()
    assert command[0]
    assert command[-1].endswith("worker.py")
    assert cwd.name == "connector_bundle"


def test_service_uses_sibling_worker_when_frozen(monkeypatch, tmp_path: Path) -> None:
    import sys

    fake_exe = tmp_path / "OpenAkita-WeChat-Connector.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    command, cwd = ConnectorService._command()
    assert command == [str(tmp_path / "OpenAkita-WeChat-Connector-Worker.exe")]
    assert cwd == tmp_path


def test_app_data_path_is_user_scoped() -> None:
    assert "OpenAkita" in str(config_service.APP_DIR)
    assert config_service.CONFIG_PATH.name == "config.yaml"
    assert config_service.LOG_PATH.name == "connector.log"
