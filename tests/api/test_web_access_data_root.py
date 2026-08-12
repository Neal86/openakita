import json
from pathlib import Path

from openakita.api.auth import WebAccessConfig, resolve_web_access_data_dir


def test_explicit_data_dir_is_authoritative(tmp_path: Path, monkeypatch):
    durable = tmp_path / "durable"
    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(durable))
    assert resolve_web_access_data_dir() == durable.resolve()
    config = WebAccessConfig(resolve_web_access_data_dir())
    config.change_password("durable-password")
    assert (durable / "web_access.json").exists()


def test_legacy_web_access_is_migrated_to_explicit_data_dir(tmp_path: Path, monkeypatch):
    from openakita import config as config_module

    project = tmp_path / "project"
    legacy_dir = project / "data"
    durable = tmp_path / "durable"
    legacy_dir.mkdir(parents=True)
    payload = {
        "jwt_secret": "a" * 64,
        "data_epoch": "epoch",
        "token_version": 7,
        "password_hash": "legacy-hash",
        "password_salt": "legacy-salt",
        "password_user_set": True,
    }
    (legacy_dir / "web_access.json").write_text(json.dumps(payload), "utf-8")
    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(durable))
    monkeypatch.setattr(config_module.settings, "project_root", project)

    resolved = resolve_web_access_data_dir()
    assert resolved == durable.resolve()
    assert json.loads((durable / "web_access.json").read_text("utf-8"))["token_version"] == 7
    assert (legacy_dir / "web_access.json").exists()


def test_existing_durable_config_wins_over_legacy(tmp_path: Path, monkeypatch):
    from openakita import config as config_module

    project = tmp_path / "project"
    legacy_dir = project / "data"
    durable = tmp_path / "durable"
    legacy_dir.mkdir(parents=True)
    durable.mkdir(parents=True)
    (legacy_dir / "web_access.json").write_text('{"token_version": 2}', "utf-8")
    (durable / "web_access.json").write_text('{"token_version": 9}', "utf-8")
    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(durable))
    monkeypatch.setattr(config_module.settings, "project_root", project)

    resolve_web_access_data_dir()
    assert json.loads((durable / "web_access.json").read_text("utf-8"))["token_version"] == 9


def test_corrupt_legacy_uses_backup_during_migration(tmp_path: Path, monkeypatch):
    from openakita import config as config_module

    project = tmp_path / "project"
    legacy_dir = project / "data"
    durable = tmp_path / "durable"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "web_access.json").write_text("{broken", "utf-8")
    (legacy_dir / "web_access.json.bak").write_text(
        '{"jwt_secret":"' + ("b" * 64) + '","data_epoch":"e","token_version":4}',
        "utf-8",
    )
    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(durable))
    monkeypatch.setattr(config_module.settings, "project_root", project)

    resolve_web_access_data_dir()
    assert json.loads((durable / "web_access.json").read_text("utf-8"))["token_version"] == 4
