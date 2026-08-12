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


def test_directory_migration_is_published_only_after_full_copy(tmp_path, monkeypatch):
    legacy_root = tmp_path / "legacy"
    durable_root = tmp_path / "durable"
    source = legacy_root / "hermes_agents"
    (source / "agent-a" / "memory").mkdir(parents=True)
    (source / "agent-a" / "memory" / "state.json").write_text('{"ok": true}', "utf-8")

    monkeypatch.setattr(paths, "_project_data_root", lambda: legacy_root)
    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(durable_root))

    target = paths.hermes_data_path("hermes_agents")

    assert (target / "agent-a" / "memory" / "state.json").read_text("utf-8") == '{"ok": true}'
    assert not list(durable_root.glob(".hermes_agents.*.migration.dir"))


def test_failed_directory_migration_leaves_no_partial_target(tmp_path, monkeypatch):
    legacy_root = tmp_path / "legacy"
    durable_root = tmp_path / "durable"
    source = legacy_root / "hermes_agents"
    source.mkdir(parents=True)
    (source / "state.txt").write_text("legacy", "utf-8")

    monkeypatch.setattr(paths, "_project_data_root", lambda: legacy_root)
    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(durable_root))

    real_copytree = paths.shutil.copytree

    def fail_after_partial_copy(src, dst, *args, **kwargs):
        real_copytree(src, dst, *args, **kwargs)
        raise OSError("copy interrupted")

    monkeypatch.setattr(paths.shutil, "copytree", fail_after_partial_copy)

    target = paths.hermes_data_path("hermes_agents")

    assert not target.exists()
    assert (source / "state.txt").read_text("utf-8") == "legacy"
    assert not list(durable_root.glob(".hermes_agents.*.migration.dir"))
