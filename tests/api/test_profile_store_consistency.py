import json

import pytest

from openakita.agents.profile import AgentProfile, AgentType, ProfileStore


def _profile(profile_id="agent-a", name="Agent A"):
    return AgentProfile(
        id=profile_id,
        name=name,
        type=AgentType.CUSTOM,
        created_by="user",
    )


def test_load_recovers_corrupt_profile_from_backup(tmp_path):
    base = tmp_path / "agents"
    profiles = base / "profiles"
    profiles.mkdir(parents=True)
    path = profiles / "agent-a.json"
    path.write_text("{broken", "utf-8")
    backup = path.with_suffix(".json.bak")
    backup.write_text(json.dumps(_profile().to_dict()), "utf-8")

    store = ProfileStore(base)

    loaded = store.get("agent-a")
    assert loaded is not None
    assert loaded.name == "Agent A"
    assert json.loads(path.read_text("utf-8"))["id"] == "agent-a"


def test_failed_new_save_does_not_publish_to_cache(tmp_path, monkeypatch):
    store = ProfileStore(tmp_path / "agents")

    def fail_persist(_profile):
        raise OSError("disk full")

    monkeypatch.setattr(store, "_persist", fail_persist)
    with pytest.raises(OSError, match="disk full"):
        store.save(_profile())
    assert store.get("agent-a") is None


def test_failed_update_keeps_previous_cached_profile(tmp_path, monkeypatch):
    store = ProfileStore(tmp_path / "agents")
    store.save(_profile())

    def fail_persist(_profile):
        raise OSError("read only")

    monkeypatch.setattr(store, "_persist", fail_persist)
    with pytest.raises(OSError, match="read only"):
        store.update("agent-a", {"name": "Changed"})

    current = store.get("agent-a")
    assert current is not None
    assert current.name == "Agent A"
