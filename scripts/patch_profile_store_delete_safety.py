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
        '''    def delete(self, profile_id: str) -> bool:\n        """删除 Profile。SYSTEM 类型禁止删除。同时清理 Profile 专属目录。"""\n        with self._lock:\n            existing = self._cache.get(profile_id)\n            if existing is None:\n                return False\n            if existing.is_system:\n                raise PermissionError(f"Cannot delete SYSTEM profile: {profile_id}")\n            del self._cache[profile_id]\n            fp = self._profiles_dir / f"{profile_id}.json"\n            if fp.exists():\n                fp.unlink()\n\n        import shutil\n\n        profile_dir = self.get_profile_dir(profile_id)\n        if profile_dir.is_dir():\n            shutil.rmtree(profile_dir, ignore_errors=True)\n            logger.info(f"ProfileStore cleaned profile dir: {profile_dir}")\n\n        logger.info(f"ProfileStore deleted: {profile_id}")\n        return True\n''',
        '''    def delete(self, profile_id: str) -> bool:\n        """Delete a custom profile without hiding data-removal failures.\n\n        Profile-owned data is removed first. If that fails, the profile remains\n        fully registered and visible so the operator can retry instead of\n        leaving an apparently deleted Agent with residual private data.\n        """\n        import shutil\n\n        with self._lock:\n            existing = self._cache.get(profile_id)\n            if existing is None:\n                return False\n            if existing.is_system:\n                raise PermissionError(f"Cannot delete SYSTEM profile: {profile_id}")\n\n            profile_dir = self.get_profile_dir(profile_id)\n            if profile_dir.is_dir():\n                shutil.rmtree(profile_dir)\n                logger.info(f"ProfileStore cleaned profile dir: {profile_dir}")\n\n            fp = self._profiles_dir / f"{profile_id}.json"\n            if fp.exists():\n                fp.unlink()\n            del self._cache[profile_id]\n\n        logger.info(f"ProfileStore deleted: {profile_id}")\n        return True\n''',
        "ProfileStore fail-closed deletion",
    )

    route = Path("src/openakita/api/routes/agents.py")
    replace_exact(
        route,
        '''    try:\n        deleted = store.delete(profile_id)\n    except PermissionError as e:\n        raise HTTPException(status_code=403, detail=str(e))\n\n    if not deleted:\n''',
        '''    try:\n        deleted = store.delete(profile_id)\n    except PermissionError as e:\n        raise HTTPException(status_code=403, detail=str(e))\n    except OSError as exc:\n        logger.error("[Agents API] Failed to delete profile %s data: %s", profile_id, exc)\n        raise HTTPException(\n            status_code=500,\n            detail="Failed to delete Agent profile data",\n        ) from exc\n\n    if not deleted:\n''',
        "Agent delete filesystem failure mapping",
    )

    test = Path("tests/api/test_profile_store_delete_safety.py")
    test.write_text(
        '''import shutil\n\nimport pytest\n\nfrom openakita.agents.profile import AgentProfile, AgentType, ProfileStore\n\n\ndef _store_with_profile(tmp_path):\n    store = ProfileStore(tmp_path / "agents")\n    profile = AgentProfile(\n        id="custom-agent",\n        name="Custom",\n        type=AgentType.CUSTOM,\n        created_by="user",\n    )\n    store.save(profile)\n    profile_dir = store.ensure_profile_dir(profile.id)\n    (profile_dir / "memory" / "private.txt").write_text("secret", "utf-8")\n    profile_json = store._profiles_dir / f"{profile.id}.json"\n    return store, profile, profile_dir, profile_json\n\n\ndef test_store_delete_failure_keeps_profile_registered(tmp_path, monkeypatch):\n    store, profile, profile_dir, profile_json = _store_with_profile(tmp_path)\n\n    def fail_remove(_path):\n        raise OSError("directory busy")\n\n    monkeypatch.setattr(shutil, "rmtree", fail_remove)\n\n    with pytest.raises(OSError, match="directory busy"):\n        store.delete(profile.id)\n\n    assert store.get(profile.id) is not None\n    assert profile_json.exists()\n    assert profile_dir.exists()\n\n\ndef test_store_delete_success_removes_data_json_and_cache(tmp_path):\n    store, profile, profile_dir, profile_json = _store_with_profile(tmp_path)\n\n    assert store.delete(profile.id) is True\n\n    assert store.get(profile.id) is None\n    assert not profile_json.exists()\n    assert not profile_dir.exists()\n''',
        "utf-8",
    )


if __name__ == "__main__":
    main()
