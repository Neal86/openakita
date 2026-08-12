from pathlib import Path


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text("utf-8")
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"{label} marker changed")
    path.write_text(text.replace(old, new, 1), "utf-8")


def main() -> None:
    profile = Path("src/openakita/agents/profile.py")
    replace_exact(
        profile,
        "from ..utils.atomic_io import atomic_json_write\n",
        "from ..utils.atomic_io import atomic_json_write, read_json_safe\n",
        "safe profile JSON import",
    )
    replace_exact(
        profile,
        '''            try:\n                data = json.loads(fp.read_text(encoding="utf-8"))\n                profile = AgentProfile.from_dict(data)\n                self._validate_profile_id(profile.id)\n''',
        '''            try:\n                data = read_json_safe(fp)\n                if not isinstance(data, dict):\n                    raise ValueError("profile JSON is not recoverable")\n                profile = AgentProfile.from_dict(data)\n                self._validate_profile_id(profile.id)\n''',
        "profile backup recovery",
    )
    replace_exact(
        profile,
        '''            existing = self._cache.get(profile.id)\n            if existing and existing.is_system:\n                self._validate_system_update(existing, profile)\n            self._cache[profile.id] = profile\n            self._persist(profile)\n''',
        '''            existing = self._cache.get(profile.id)\n            if existing and existing.is_system:\n                self._validate_system_update(existing, profile)\n            self._persist(profile)\n            self._cache[profile.id] = profile\n''',
        "save cache after disk",
    )
    replace_exact(
        profile,
        '''            data.update(updates)\n            profile = AgentProfile.from_dict(data)\n            self._cache[profile_id] = profile\n            self._persist(profile)\n\n        logger.info(f"ProfileStore updated: {profile_id}")\n''',
        '''            data.update(updates)\n            profile = AgentProfile.from_dict(data)\n            self._persist(profile)\n            self._cache[profile_id] = profile\n\n        logger.info(f"ProfileStore updated: {profile_id}")\n''',
        "update cache after disk",
    )
    replace_exact(
        profile,
        '''    def _persist(self, profile: AgentProfile) -> None:\n        profile_id = self._validate_profile_id(profile.id)\n        fp = self._profiles_dir / f"{profile_id}.json"\n        atomic_json_write(fp, profile.to_dict())\n''',
        '''    def _persist(self, profile: AgentProfile) -> None:\n        profile_id = self._validate_profile_id(profile.id)\n        fp = self._profiles_dir / f"{profile_id}.json"\n        atomic_json_write(\n            fp,\n            profile.to_dict(),\n            backup=True,\n            fsync=True,\n            allow_fallback=False,\n        )\n''',
        "fail-closed profile persistence",
    )

    hub = Path("src/openakita/api/routes/hub.py")
    replace_exact(
        hub,
        '''            profile = AgentProfile.from_dict(pdata)\n            profile_store.save(profile)\n            _write_profile_identity_files(profile_store, profile.id, identity_files)\n''',
        '''            profile = AgentProfile.from_dict(pdata)\n            try:\n                profile_store.save(profile)\n            except ValueError as exc:\n                raise HTTPException(\n                    status_code=400,\n                    detail=f"Invalid Agent profile: {exc}",\n                ) from exc\n            _write_profile_identity_files(profile_store, profile.id, identity_files)\n''',
        "invalid imported profile is a 400",
    )

    test = Path("tests/api/test_profile_store_consistency.py")
    test.write_text(
        '''import json\n\nimport pytest\n\nfrom openakita.agents.profile import AgentProfile, AgentType, ProfileStore\n\n\ndef _profile(profile_id="agent-a", name="Agent A"):\n    return AgentProfile(\n        id=profile_id,\n        name=name,\n        type=AgentType.CUSTOM,\n        created_by="user",\n    )\n\n\ndef test_load_recovers_corrupt_profile_from_backup(tmp_path):\n    base = tmp_path / "agents"\n    profiles = base / "profiles"\n    profiles.mkdir(parents=True)\n    path = profiles / "agent-a.json"\n    path.write_text("{broken", "utf-8")\n    backup = path.with_suffix(".json.bak")\n    backup.write_text(json.dumps(_profile().to_dict()), "utf-8")\n\n    store = ProfileStore(base)\n\n    loaded = store.get("agent-a")\n    assert loaded is not None\n    assert loaded.name == "Agent A"\n    assert json.loads(path.read_text("utf-8"))["id"] == "agent-a"\n\n\ndef test_failed_new_save_does_not_publish_to_cache(tmp_path, monkeypatch):\n    store = ProfileStore(tmp_path / "agents")\n\n    def fail_persist(_profile):\n        raise OSError("disk full")\n\n    monkeypatch.setattr(store, "_persist", fail_persist)\n    with pytest.raises(OSError, match="disk full"):\n        store.save(_profile())\n    assert store.get("agent-a") is None\n\n\ndef test_failed_update_keeps_previous_cached_profile(tmp_path, monkeypatch):\n    store = ProfileStore(tmp_path / "agents")\n    store.save(_profile())\n\n    def fail_persist(_profile):\n        raise OSError("read only")\n\n    monkeypatch.setattr(store, "_persist", fail_persist)\n    with pytest.raises(OSError, match="read only"):\n        store.update("agent-a", {"name": "Changed"})\n\n    current = store.get("agent-a")\n    assert current is not None\n    assert current.name == "Agent A"\n''',
        "utf-8",
    )


if __name__ == "__main__":
    main()
