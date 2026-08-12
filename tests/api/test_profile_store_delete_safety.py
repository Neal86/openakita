import shutil

import pytest

from openakita.agents.profile import AgentProfile, AgentType, ProfileStore


def _store_with_profile(tmp_path):
    base_dir = tmp_path / "agents"
    store = ProfileStore(base_dir)
    profile = AgentProfile(
        id="custom-agent",
        name="Custom",
        type=AgentType.CUSTOM,
        created_by="user",
    )
    store.save(profile)
    profile_dir = store.ensure_profile_dir(profile.id)
    (profile_dir / "memory" / "private.txt").write_text("secret", "utf-8")
    profile_json = base_dir / "profiles" / f"{profile.id}.json"
    return store, profile, profile_dir, profile_json


def test_store_delete_failure_keeps_profile_registered(tmp_path, monkeypatch):
    store, profile, profile_dir, profile_json = _store_with_profile(tmp_path)

    def fail_remove(_path):
        raise OSError("directory busy")

    monkeypatch.setattr(shutil, "rmtree", fail_remove)

    with pytest.raises(OSError, match="directory busy"):
        store.delete(profile.id)

    assert store.get(profile.id) is not None
    assert profile_json.exists()
    assert profile_dir.exists()


def test_store_delete_success_removes_data_json_and_cache(tmp_path):
    store, profile, profile_dir, profile_json = _store_with_profile(tmp_path)

    assert store.delete(profile.id) is True

    assert store.get(profile.id) is None
    assert not profile_json.exists()
    assert not profile_dir.exists()


@pytest.mark.parametrize(
    "profile_id",
    ["../escape", "..\\escape", ".", "..", "profiles", " leading", "trailing "],
)
def test_store_rejects_unsafe_profile_ids_before_any_write(tmp_path, profile_id):
    base_dir = tmp_path / "agents"
    store = ProfileStore(base_dir)
    profile = AgentProfile(
        id=profile_id,
        name="Unsafe",
        type=AgentType.CUSTOM,
        created_by="import",
    )

    with pytest.raises(ValueError):
        store.save(profile)

    assert list((base_dir / "profiles").glob("*.json")) == []
    assert not (tmp_path / "escape.json").exists()
    assert not (tmp_path / "escape").exists()
