from __future__ import annotations

import json

from openakita.hermes import paths
from openakita.utils.atomic_io import read_json_safe


def test_file_migration_preserves_backup_for_recovery(tmp_path, monkeypatch):
    legacy_root = tmp_path / "legacy"
    durable_root = tmp_path / "durable"
    legacy_root.mkdir()
    primary = legacy_root / "agent_execution.json"
    backup = primary.with_suffix(".json.bak")
    primary.write_text("{broken", "utf-8")
    backup.write_text(json.dumps({"agents": [{"profile_id": "safe"}]}), "utf-8")

    monkeypatch.setattr(paths, "_project_data_root", lambda: legacy_root)
    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(durable_root))

    target = paths.hermes_data_path("agent_execution.json")

    assert target.exists()
    assert target.with_suffix(".json.bak").exists()
    recovered = read_json_safe(target)
    assert recovered == {"agents": [{"profile_id": "safe"}]}
    assert json.loads(target.read_text("utf-8")) == recovered


def test_backup_only_migration_seeds_durable_primary(tmp_path, monkeypatch):
    legacy_root = tmp_path / "legacy"
    durable_root = tmp_path / "durable"
    legacy_root.mkdir()
    primary = legacy_root / "hermes_instances.json"
    backup = primary.with_suffix(".json.bak")
    backup.write_text(json.dumps({"instances": []}), "utf-8")

    monkeypatch.setattr(paths, "_project_data_root", lambda: legacy_root)
    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(durable_root))

    target = paths.hermes_data_path("hermes_instances.json")

    assert json.loads(target.read_text("utf-8")) == {"instances": []}
    assert json.loads(target.with_suffix(".json.bak").read_text("utf-8")) == {"instances": []}
