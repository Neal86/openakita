from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from openakita.api.routes import agents


class _FakeStore:
    def __init__(self, profile_dir):
        self.profile_dir = profile_dir
        self.updates = []

    def get(self, profile_id):
        return SimpleNamespace(id=profile_id)

    def get_profile_dir(self, profile_id):
        return self.profile_dir

    def ensure_profile_dir(self, profile_id):
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        return self.profile_dir

    def update(self, profile_id, payload):
        self.updates.append((profile_id, payload))
        return SimpleNamespace(id=profile_id)


@pytest.mark.asyncio
async def test_profile_data_delete_failure_does_not_report_success_or_change_modes(
    tmp_path, monkeypatch
):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "memory.db").write_text("data", "utf-8")
    store = _FakeStore(profile_dir)

    from openakita.agents import profile as profile_module

    monkeypatch.setattr(profile_module, "get_profile_store", lambda: store)

    import shutil

    def fail_remove(_path):
        raise OSError("disk is read-only")

    monkeypatch.setattr(shutil, "rmtree", fail_remove)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    with pytest.raises(HTTPException) as exc_info:
        await agents.delete_profile_data("agent-a", request)

    assert exc_info.value.status_code == 500
    assert store.updates == []
    assert profile_dir.exists()


@pytest.mark.asyncio
async def test_profile_data_modes_change_only_after_successful_delete(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "memory.db").write_text("data", "utf-8")
    store = _FakeStore(profile_dir)

    from openakita.agents import profile as profile_module

    monkeypatch.setattr(profile_module, "get_profile_store", lambda: store)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    result = await agents.delete_profile_data("agent-a", request)

    assert result == {"status": "ok"}
    assert not profile_dir.exists()
    assert store.updates == [
        (
            "agent-a",
            {
                "identity_mode": "shared",
                "memory_mode": "shared",
                "memory_inherit_global": True,
            },
        )
    ]


@pytest.mark.asyncio
async def test_identity_write_failure_preserves_previous_file(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    identity_dir = profile_dir / "identity"
    identity_dir.mkdir(parents=True)
    identity_file = identity_dir / "SOUL.md"
    identity_file.write_text("old identity", "utf-8")
    store = _FakeStore(profile_dir)

    from openakita.agents import profile as profile_module
    from openakita.utils import atomic_io

    monkeypatch.setattr(profile_module, "get_profile_store", lambda: store)

    def fail_write(*_args, **_kwargs):
        raise OSError("disk write failed")

    monkeypatch.setattr(atomic_io, "safe_write", fail_write)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    with pytest.raises(HTTPException) as exc_info:
        await agents.write_profile_identity_file(
            "agent-a",
            "SOUL.md",
            agents.IdentityFileRequest(content="new identity"),
            request,
        )

    assert exc_info.value.status_code == 500
    assert identity_file.read_text("utf-8") == "old identity"


@pytest.mark.asyncio
async def test_identity_write_uses_atomic_backup(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    identity_dir = profile_dir / "identity"
    identity_dir.mkdir(parents=True)
    identity_file = identity_dir / "SOUL.md"
    identity_file.write_text("old identity", "utf-8")
    store = _FakeStore(profile_dir)

    from openakita.agents import profile as profile_module

    monkeypatch.setattr(profile_module, "get_profile_store", lambda: store)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    result = await agents.write_profile_identity_file(
        "agent-a",
        "SOUL.md",
        agents.IdentityFileRequest(content="new identity"),
        request,
    )

    assert result == {"status": "ok", "filename": "SOUL.md"}
    assert identity_file.read_text("utf-8") == "new identity"
    assert identity_file.with_suffix(".md.bak").read_text("utf-8") == "old identity"
