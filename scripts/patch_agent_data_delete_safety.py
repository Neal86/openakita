from pathlib import Path


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text("utf-8")
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"{label} marker changed")
    path.write_text(text.replace(old, new, 1), "utf-8")


def main() -> None:
    route = Path("src/openakita/api/routes/agents.py")
    replace_exact(
        route,
        '''    profile_dir = store.get_profile_dir(profile_id)\n    if profile_dir.is_dir():\n        shutil.rmtree(profile_dir, ignore_errors=True)\n\n    store.update(\n''',
        '''    profile_dir = store.get_profile_dir(profile_id)\n    if profile_dir.is_dir():\n        try:\n            shutil.rmtree(profile_dir)\n        except OSError as exc:\n            logger.error(\n                "[Agents API] Failed to delete profile data for %s: %s",\n                profile_id,\n                exc,\n            )\n            raise HTTPException(\n                status_code=500,\n                detail="Failed to delete Agent profile data",\n            ) from exc\n\n    store.update(\n''',
        "profile data deletion must fail closed",
    )

    test = Path("tests/api/test_agent_data_delete_safety.py")
    test.write_text(
        '''from types import SimpleNamespace\n\nimport pytest\nfrom fastapi import HTTPException\n\nfrom openakita.api.routes import agents\n\n\nclass _FakeStore:\n    def __init__(self, profile_dir):\n        self.profile_dir = profile_dir\n        self.updates = []\n\n    def get(self, profile_id):\n        return SimpleNamespace(id=profile_id)\n\n    def get_profile_dir(self, profile_id):\n        return self.profile_dir\n\n    def update(self, profile_id, payload):\n        self.updates.append((profile_id, payload))\n        return SimpleNamespace(id=profile_id)\n\n\n@pytest.mark.asyncio\nasync def test_profile_data_delete_failure_does_not_report_success_or_change_modes(\n    tmp_path, monkeypatch\n):\n    profile_dir = tmp_path / "profile"\n    profile_dir.mkdir()\n    (profile_dir / "memory.db").write_text("data", "utf-8")\n    store = _FakeStore(profile_dir)\n\n    from openakita.agents import profile as profile_module\n\n    monkeypatch.setattr(profile_module, "get_profile_store", lambda: store)\n\n    import shutil\n\n    def fail_remove(_path):\n        raise OSError("disk is read-only")\n\n    monkeypatch.setattr(shutil, "rmtree", fail_remove)\n    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))\n\n    with pytest.raises(HTTPException) as exc_info:\n        await agents.delete_profile_data("agent-a", request)\n\n    assert exc_info.value.status_code == 500\n    assert store.updates == []\n    assert profile_dir.exists()\n\n\n@pytest.mark.asyncio\nasync def test_profile_data_modes_change_only_after_successful_delete(tmp_path, monkeypatch):\n    profile_dir = tmp_path / "profile"\n    profile_dir.mkdir()\n    (profile_dir / "memory.db").write_text("data", "utf-8")\n    store = _FakeStore(profile_dir)\n\n    from openakita.agents import profile as profile_module\n\n    monkeypatch.setattr(profile_module, "get_profile_store", lambda: store)\n    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))\n\n    result = await agents.delete_profile_data("agent-a", request)\n\n    assert result == {"status": "ok"}\n    assert not profile_dir.exists()\n    assert store.updates == [\n        (\n            "agent-a",\n            {\n                "identity_mode": "shared",\n                "memory_mode": "shared",\n                "memory_inherit_global": True,\n            },\n        )\n    ]\n''',
        "utf-8",
    )


if __name__ == "__main__":
    main()
