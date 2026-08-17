from pathlib import Path

from openakita.agents import profile as profile_module
from openakita.agents.profile import ProfileStore


def test_system_preset_is_resolved_even_when_not_persisted(tmp_path: Path, monkeypatch):
    store = ProfileStore(tmp_path / 'agents')
    monkeypatch.setattr(profile_module, '_global_store', store)
    assert not store.exists('default')
    resolved = profile_module.resolve_agent_profile('default')
    assert resolved is not None
    assert resolved.id == 'default'
    assert profile_module.agent_profile_exists('default')
    assert not profile_module.agent_profile_exists('definitely-missing-agent')
