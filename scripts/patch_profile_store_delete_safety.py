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
        '''    def save(self, profile: AgentProfile) -> None:\n        """保存 Profile。ephemeral=True 的只存内存，否则写磁盘。"""\n        with self._lock:\n            if profile.ephemeral:\n''',
        '''    def save(self, profile: AgentProfile) -> None:\n        """保存 Profile。ephemeral=True 的只存内存，否则写磁盘。"""\n        self._validate_profile_id(profile.id)\n        with self._lock:\n            if profile.ephemeral:\n''',
        "validate profile id on save",
    )
    replace_exact(
        profile,
        '''    _RESERVED_DIR_NAMES = frozenset({"profiles"})\n\n    def get_profile_dir(self, profile_id: str) -> Path:\n        """返回 Profile 专属数据目录 data/agents/{profile_id}/\n\n        Raises ValueError if profile_id collides with reserved directory names.\n        """\n        if profile_id in self._RESERVED_DIR_NAMES:\n            raise ValueError(f"Profile ID '{profile_id}' conflicts with a reserved directory name")\n        return self._base_dir / profile_id\n''',
        '''    _RESERVED_DIR_NAMES = frozenset({"profiles"})\n\n    @classmethod\n    def _validate_profile_id(cls, profile_id: str) -> str:\n        """Reject IDs that can escape the Agent storage root on any platform."""\n        if not isinstance(profile_id, str) or not profile_id:\n            raise ValueError("Profile ID must be a non-empty string")\n        if profile_id != profile_id.strip():\n            raise ValueError("Profile ID must not contain leading or trailing whitespace")\n        if (\n            profile_id in cls._RESERVED_DIR_NAMES\n            or profile_id in {".", ".."}\n            or "/" in profile_id\n            or "\\\\" in profile_id\n            or "\\x00" in profile_id\n        ):\n            raise ValueError(f"Unsafe Profile ID: {profile_id!r}")\n        return profile_id\n\n    def get_profile_dir(self, profile_id: str) -> Path:\n        """返回 Profile 专属数据目录 data/agents/{profile_id}/。"""\n        profile_id = self._validate_profile_id(profile_id)\n        return self._base_dir / profile_id\n''',
        "ProfileStore path-safe profile ids",
    )
    replace_exact(
        profile,
        '''    def _persist(self, profile: AgentProfile) -> None:\n        fp = self._profiles_dir / f"{profile.id}.json"\n        atomic_json_write(fp, profile.to_dict())\n''',
        '''    def _persist(self, profile: AgentProfile) -> None:\n        profile_id = self._validate_profile_id(profile.id)\n        fp = self._profiles_dir / f"{profile_id}.json"\n        atomic_json_write(fp, profile.to_dict())\n''',
        "validate profile id before persistence",
    )
    replace_exact(
        profile,
        '''                data = json.loads(fp.read_text(encoding="utf-8"))\n                profile = AgentProfile.from_dict(data)\n                profile = self._heal_loaded_profile(profile, fp)\n''',
        '''                data = json.loads(fp.read_text(encoding="utf-8"))\n                profile = AgentProfile.from_dict(data)\n                self._validate_profile_id(profile.id)\n                profile = self._heal_loaded_profile(profile, fp)\n''',
        "reject unsafe profile ids on load",
    )
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

    hub = Path("src/openakita/api/routes/hub.py")
    replace_exact(
        hub,
        '''        if not isinstance(content, str):\n            continue\n        (identity_dir / filename).write_text(content, encoding="utf-8")\n''',
        '''        if not isinstance(content, str):\n            continue\n        from openakita.utils.atomic_io import safe_write\n\n        safe_write(\n            identity_dir / filename,\n            content,\n            backup=True,\n            fsync=True,\n            allow_fallback=False,\n        )\n''',
        "atomic imported identity writes",
    )

    test = Path("tests/api/test_profile_store_delete_safety.py")
    test.write_text(
        '''import shutil\n\nimport pytest\n\nfrom openakita.agents.profile import AgentProfile, AgentType, ProfileStore\nfrom openakita.api.routes.hub import _write_profile_identity_files\n\n\ndef _store_with_profile(tmp_path):\n    base_dir = tmp_path / "agents"\n    store = ProfileStore(base_dir)\n    profile = AgentProfile(\n        id="custom-agent",\n        name="Custom",\n        type=AgentType.CUSTOM,\n        created_by="user",\n    )\n    store.save(profile)\n    profile_dir = store.ensure_profile_dir(profile.id)\n    (profile_dir / "memory" / "private.txt").write_text("secret", "utf-8")\n    profile_json = base_dir / "profiles" / f"{profile.id}.json"\n    return store, profile, profile_dir, profile_json\n\n\ndef test_store_delete_failure_keeps_profile_registered(tmp_path, monkeypatch):\n    store, profile, profile_dir, profile_json = _store_with_profile(tmp_path)\n\n    def fail_remove(_path):\n        raise OSError("directory busy")\n\n    monkeypatch.setattr(shutil, "rmtree", fail_remove)\n\n    with pytest.raises(OSError, match="directory busy"):\n        store.delete(profile.id)\n\n    assert store.get(profile.id) is not None\n    assert profile_json.exists()\n    assert profile_dir.exists()\n\n\ndef test_store_delete_success_removes_data_json_and_cache(tmp_path):\n    store, profile, profile_dir, profile_json = _store_with_profile(tmp_path)\n\n    assert store.delete(profile.id) is True\n\n    assert store.get(profile.id) is None\n    assert not profile_json.exists()\n    assert not profile_dir.exists()\n\n\n@pytest.mark.parametrize(\n    "profile_id",\n    ["../escape", "..\\\\escape", ".", "..", "profiles", " leading", "trailing "],\n)\ndef test_store_rejects_unsafe_profile_ids_before_any_write(tmp_path, profile_id):\n    base_dir = tmp_path / "agents"\n    store = ProfileStore(base_dir)\n    profile = AgentProfile(\n        id=profile_id,\n        name="Unsafe",\n        type=AgentType.CUSTOM,\n        created_by="import",\n    )\n\n    with pytest.raises(ValueError):\n        store.save(profile)\n\n    assert list((base_dir / "profiles").glob("*.json")) == []\n    assert not (tmp_path / "escape.json").exists()\n    assert not (tmp_path / "escape").exists()\n\n\ndef test_imported_identity_write_is_atomic_and_keeps_backup(tmp_path):\n    store, profile, profile_dir, _ = _store_with_profile(tmp_path)\n    identity_file = profile_dir / "identity" / "SOUL.md"\n    identity_file.write_text("old identity", "utf-8")\n\n    _write_profile_identity_files(\n        store,\n        profile.id,\n        {"SOUL.md": "new identity"},\n    )\n\n    assert identity_file.read_text("utf-8") == "new identity"\n    assert identity_file.with_suffix(".md.bak").read_text("utf-8") == "old identity"\n''',
        "utf-8",
    )


if __name__ == "__main__":
    main()
