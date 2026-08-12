from pathlib import Path


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text("utf-8")
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"{label} marker changed")
    path.write_text(text.replace(old, new, 1), "utf-8")


def main() -> None:
    auth = Path("src/openakita/api/auth.py")
    text = auth.read_text("utf-8")
    text = text.replace("import secrets\nimport shutil\nimport threading\n", "import secrets\nimport threading\n", 1)
    auth.write_text(text, "utf-8")

    old_doc = '''    ``OPENAKITA_DATA_DIR`` is authoritative for container/VPS deployments.\n    Otherwise reuse ``settings.data_dir`` when available, with the historical\n    ``project_root/data`` directory as fallback. If an explicit durable root\n    is newly introduced, copy the legacy authentication file once so upgrades\n    do not silently forget the user's password/JWT identity.\n'''
    new_doc = '''    ``OPENAKITA_DATA_DIR`` is authoritative for container/VPS deployments.\n    Otherwise reuse ``settings.data_dir`` when available, with the historical\n    ``project_root/data`` directory as fallback. When a durable root is newly\n    introduced, migrate only the authentication JSON and do so through the\n    existing validated atomic-I/O path. Other server data keeps its historical\n    location unless it has its own explicit persistence migration.\n'''
    replace_exact(auth, old_doc, new_doc, "web access data root docstring")

    old = '''            if not target_file.exists() and legacy_file.exists():\n                try:\n                    shutil.copy2(legacy_file, target_file)\n                    backup = legacy_file.with_suffix(legacy_file.suffix + ".bak")\n                    if backup.exists():\n                        shutil.copy2(backup, target_file.with_suffix(target_file.suffix + ".bak"))\n                    logger.info(\n                        "Migrated web access config from %s to durable root %s",\n                        legacy_file,\n                        target_file,\n                    )\n                except OSError as exc:\n                    logger.warning(\n                        "Failed to migrate web access config from %s to %s: %s",\n                        legacy_file,\n                        target_file,\n                        exc,\n                    )\n'''
    new = '''            if not target_file.exists() and legacy_file.exists():\n                legacy_data = read_json_safe(legacy_file)\n                if isinstance(legacy_data, dict):\n                    try:\n                        atomic_json_write(\n                            target_file,\n                            legacy_data,\n                            backup=True,\n                            fsync=True,\n                            allow_fallback=False,\n                        )\n                        logger.info(\n                            "Migrated web access config from %s to durable root %s",\n                            legacy_file,\n                            target_file,\n                        )\n                    except OSError as exc:\n                        logger.warning(\n                            "Failed to migrate web access config from %s to %s: %s",\n                            legacy_file,\n                            target_file,\n                            exc,\n                        )\n                else:\n                    logger.error(\n                        "Legacy web access config %s is not recoverable; "\n                        "leaving durable target absent",\n                        legacy_file,\n                    )\n'''
    replace_exact(auth, old, new, "atomic legacy auth migration")

    test = Path("tests/api/test_web_access_data_root.py")
    test.write_text(
        '''import json\nfrom pathlib import Path\n\nfrom openakita.api.auth import WebAccessConfig, resolve_web_access_data_dir\n\n\ndef test_explicit_data_dir_is_authoritative(tmp_path: Path, monkeypatch):\n    durable = tmp_path / "durable"\n    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(durable))\n    assert resolve_web_access_data_dir() == durable.resolve()\n    config = WebAccessConfig(resolve_web_access_data_dir())\n    config.change_password("durable-password")\n    assert (durable / "web_access.json").exists()\n\n\ndef test_legacy_web_access_is_migrated_to_explicit_data_dir(tmp_path: Path, monkeypatch):\n    from openakita import config as config_module\n\n    project = tmp_path / "project"\n    legacy_dir = project / "data"\n    durable = tmp_path / "durable"\n    legacy_dir.mkdir(parents=True)\n    payload = {\n        "jwt_secret": "a" * 64,\n        "data_epoch": "epoch",\n        "token_version": 7,\n        "password_hash": "legacy-hash",\n        "password_salt": "legacy-salt",\n        "password_user_set": True,\n    }\n    (legacy_dir / "web_access.json").write_text(json.dumps(payload), "utf-8")\n    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(durable))\n    monkeypatch.setattr(config_module.settings, "project_root", project)\n\n    resolved = resolve_web_access_data_dir()\n    assert resolved == durable.resolve()\n    assert json.loads((durable / "web_access.json").read_text("utf-8"))["token_version"] == 7\n    assert (legacy_dir / "web_access.json").exists()\n\n\ndef test_existing_durable_config_wins_over_legacy(tmp_path: Path, monkeypatch):\n    from openakita import config as config_module\n\n    project = tmp_path / "project"\n    legacy_dir = project / "data"\n    durable = tmp_path / "durable"\n    legacy_dir.mkdir(parents=True)\n    durable.mkdir(parents=True)\n    (legacy_dir / "web_access.json").write_text('{"token_version": 2}', "utf-8")\n    (durable / "web_access.json").write_text('{"token_version": 9}', "utf-8")\n    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(durable))\n    monkeypatch.setattr(config_module.settings, "project_root", project)\n\n    resolve_web_access_data_dir()\n    assert json.loads((durable / "web_access.json").read_text("utf-8"))["token_version"] == 9\n\n\ndef test_corrupt_legacy_uses_backup_during_migration(tmp_path: Path, monkeypatch):\n    from openakita import config as config_module\n\n    project = tmp_path / "project"\n    legacy_dir = project / "data"\n    durable = tmp_path / "durable"\n    legacy_dir.mkdir(parents=True)\n    (legacy_dir / "web_access.json").write_text("{broken", "utf-8")\n    (legacy_dir / "web_access.json.bak").write_text(\n        '{"jwt_secret":"' + ("b" * 64) + '","data_epoch":"e","token_version":4}',\n        "utf-8",\n    )\n    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(durable))\n    monkeypatch.setattr(config_module.settings, "project_root", project)\n\n    resolve_web_access_data_dir()\n    assert json.loads((durable / "web_access.json").read_text("utf-8"))["token_version"] == 4\n''',
        "utf-8",
    )


if __name__ == "__main__":
    main()
