from pathlib import Path

route = Path("src/openakita/api/routes/windows_connector.py")
text = route.read_text("utf-8")
old = '''def _data_dir() -> Path:\n    configured = os.environ.get("OPENAKITA_DATA_DIR", "").strip()\n    if configured:\n        return Path(configured).expanduser().resolve()\n    return Path.home() / ".openakita" / "data"\n'''
new = '''def _data_dir() -> Path:\n    configured = os.environ.get("OPENAKITA_DATA_DIR", "").strip()\n    if configured:\n        return Path(configured).expanduser().resolve()\n    try:\n        from openakita.config import settings\n\n        return Path(settings.data_dir).resolve()\n    except Exception:\n        return Path.home() / ".openakita" / "data"\n'''
if old not in text:
    if new not in text:
        raise SystemExit("windows connector data_dir marker changed")
else:
    route.write_text(text.replace(old, new, 1), "utf-8")

test = Path("tests/windows_connector/test_data_dir.py")
test.write_text('''from openakita.api.routes import windows_connector as route\n\n\ndef test_data_dir_prefers_environment(tmp_path, monkeypatch):\n    env_dir = tmp_path / "env-data"\n    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(env_dir))\n    assert route._data_dir() == env_dir.resolve()\n\n\ndef test_data_dir_uses_settings_when_env_missing(tmp_path, monkeypatch):\n    monkeypatch.delenv("OPENAKITA_DATA_DIR", raising=False)\n    from openakita.config import settings\n\n    configured = tmp_path / "configured-data"\n    monkeypatch.setattr(settings, "data_dir", configured)\n    assert route._data_dir() == configured.resolve()\n''', "utf-8")
