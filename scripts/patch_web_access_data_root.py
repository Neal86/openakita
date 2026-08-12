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
    replace_exact(
        auth,
        "import secrets\nimport threading\nimport time\nfrom pathlib import Path\n",
        "import secrets\nimport shutil\nimport threading\nimport time\nfrom pathlib import Path\n",
        "auth shutil import",
    )
    marker = "# ---------------------------------------------------------------------------\n# Web Access config (data/web_access.json)\n# ---------------------------------------------------------------------------\n\n\n"
    helper = '''# ---------------------------------------------------------------------------\n# Web Access config (durable data root)\n# ---------------------------------------------------------------------------\n\n\ndef resolve_web_access_data_dir() -> Path:\n    """Return the durable directory that owns ``web_access.json``.\n\n    ``OPENAKITA_DATA_DIR`` is authoritative for container/VPS deployments.\n    Otherwise reuse ``settings.data_dir`` when available, with the historical\n    ``project_root/data`` directory as fallback. If an explicit durable root\n    is newly introduced, copy the legacy authentication file once so upgrades\n    do not silently forget the user's password/JWT identity.\n    """\n    explicit = os.environ.get("OPENAKITA_DATA_DIR", "").strip()\n    legacy = Path.cwd() / "data"\n    if explicit:\n        target = Path(explicit).expanduser().resolve()\n        try:\n            from openakita.config import settings\n\n            legacy = (Path(settings.project_root) / "data").resolve()\n        except Exception:\n            legacy = legacy.resolve()\n    else:\n        try:\n            from openakita.config import settings\n\n            legacy = (Path(settings.project_root) / "data").resolve()\n            configured = getattr(settings, "data_dir", None)\n            target = Path(configured).expanduser() if configured else legacy\n            if not target.is_absolute():\n                target = Path(settings.project_root) / target\n            target = target.resolve()\n        except Exception:\n            target = legacy.resolve()\n\n    target.mkdir(parents=True, exist_ok=True)\n    target_file = target / "web_access.json"\n    legacy_file = legacy / "web_access.json"\n    if target != legacy and not target_file.exists() and legacy_file.exists():\n        migration_lock = FileLock(str(target_file) + ".migration.lock")\n        with migration_lock:\n            if not target_file.exists() and legacy_file.exists():\n                try:\n                    shutil.copy2(legacy_file, target_file)\n                    backup = legacy_file.with_suffix(legacy_file.suffix + ".bak")\n                    if backup.exists():\n                        shutil.copy2(backup, target_file.with_suffix(target_file.suffix + ".bak"))\n                    logger.info(\n                        "Migrated web access config from %s to durable root %s",\n                        legacy_file,\n                        target_file,\n                    )\n                except OSError as exc:\n                    logger.warning(\n                        "Failed to migrate web access config from %s to %s: %s",\n                        legacy_file,\n                        target_file,\n                        exc,\n                    )\n    return target\n\n\n'''
    replace_exact(auth, marker, helper, "web access data root helper")

    server = Path("src/openakita/api/server.py")
    replace_exact(
        server,
        "from .auth import WebAccessConfig, create_auth_middleware\n",
        "from .auth import (\n    WebAccessConfig,\n    create_auth_middleware,\n    resolve_web_access_data_dir,\n)\n",
        "server auth imports",
    )
    old_server = '''    try:\n        from openakita.config import settings\n\n        data_dir = Path(settings.project_root) / "data"\n    except Exception:\n        data_dir = Path.cwd() / "data"\n    web_access_config = WebAccessConfig(data_dir)\n'''
    new_server = '''    web_access_config = WebAccessConfig(resolve_web_access_data_dir())\n'''
    replace_exact(server, old_server, new_server, "server WebAccessConfig root")

    main_path = Path("src/openakita/main.py")
    old_main = '''def _web_password_already_set() -> bool:\n    """PR-L1: 检查 data/web_access.json 是否已经存了哈希密码。\n\n    用于 lan_mode 开启时的安全闸：只要本机已配置过密码，就允许 0.0.0.0；\n    否则拒绝启动，避免无密码裸奔。\n    """\n    try:\n        ws = settings.user_workspace_path\n        web_access = Path(ws) / "data" / "web_access.json"\n        if not web_access.exists():\n            return False\n        import json as _json\n\n        data = _json.loads(web_access.read_text(encoding="utf-8"))\n        return bool(data.get("password_hash") or data.get("hash"))\n    except Exception:\n        return False\n'''
    new_main = '''def _web_password_already_set() -> bool:\n    """Return whether the durable web-access config contains a password hash."""\n    try:\n        from .api.auth import resolve_web_access_data_dir\n        from .utils.atomic_io import read_json_safe\n\n        data = read_json_safe(resolve_web_access_data_dir() / "web_access.json")\n        if not isinstance(data, dict):\n            return False\n        return bool(data.get("password_hash") or data.get("hash"))\n    except Exception:\n        return False\n'''
    replace_exact(main_path, old_main, new_main, "LAN password gate")

    test = Path("tests/api/test_web_access_data_root.py")
    test.write_text(
        '''import json\nfrom pathlib import Path\n\nfrom openakita.api.auth import WebAccessConfig, resolve_web_access_data_dir\n\n\ndef test_explicit_data_dir_is_authoritative(tmp_path: Path, monkeypatch):\n    durable = tmp_path / "durable"\n    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(durable))\n    assert resolve_web_access_data_dir() == durable.resolve()\n    config = WebAccessConfig(resolve_web_access_data_dir())\n    config.change_password("durable-password")\n    assert (durable / "web_access.json").exists()\n\n\ndef test_legacy_web_access_is_migrated_to_explicit_data_dir(tmp_path: Path, monkeypatch):\n    from openakita import config as config_module\n\n    project = tmp_path / "project"\n    legacy_dir = project / "data"\n    durable = tmp_path / "durable"\n    legacy_dir.mkdir(parents=True)\n    payload = {\n        "jwt_secret": "a" * 64,\n        "data_epoch": "epoch",\n        "token_version": 7,\n        "password_hash": "legacy-hash",\n        "password_salt": "legacy-salt",\n        "password_user_set": True,\n    }\n    (legacy_dir / "web_access.json").write_text(json.dumps(payload), "utf-8")\n    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(durable))\n    monkeypatch.setattr(config_module.settings, "project_root", project)\n\n    resolved = resolve_web_access_data_dir()\n    assert resolved == durable.resolve()\n    assert json.loads((durable / "web_access.json").read_text("utf-8"))["token_version"] == 7\n    assert (legacy_dir / "web_access.json").exists()\n\n\ndef test_existing_durable_config_wins_over_legacy(tmp_path: Path, monkeypatch):\n    from openakita import config as config_module\n\n    project = tmp_path / "project"\n    legacy_dir = project / "data"\n    durable = tmp_path / "durable"\n    legacy_dir.mkdir(parents=True)\n    durable.mkdir(parents=True)\n    (legacy_dir / "web_access.json").write_text('{"token_version": 2}', "utf-8")\n    (durable / "web_access.json").write_text('{"token_version": 9}', "utf-8")\n    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(durable))\n    monkeypatch.setattr(config_module.settings, "project_root", project)\n\n    resolve_web_access_data_dir()\n    assert json.loads((durable / "web_access.json").read_text("utf-8"))["token_version"] == 9\n''',
        "utf-8",
    )


if __name__ == "__main__":
    main()
