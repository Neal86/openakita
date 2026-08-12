from pathlib import Path


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text("utf-8")
    if old not in text:
        raise SystemExit(f"{label} pattern changed; refusing broad edit")
    path.write_text(text.replace(old, new, 1), "utf-8")


def main() -> None:
    replace_exact(
        Path("src/openakita/agents/profile.py"),
        "        _global_store = ProfileStore(base_dir)\n        return _global_store\n\n\nclass ProfileStore:",
        "        _global_store = ProfileStore(base_dir)\n        return _global_store\n\n\ndef resolve_agent_profile(profile_id: str) -> AgentProfile | None:\n    \"\"\"Resolve a persisted/ephemeral profile or an undeployed system preset.\"\"\"\n    profile = get_profile_store().get(profile_id)\n    if profile is not None:\n        return profile\n    from openakita.agents.presets import get_preset_by_id\n\n    return get_preset_by_id(profile_id)\n\n\ndef agent_profile_exists(profile_id: str) -> bool:\n    return resolve_agent_profile(profile_id) is not None\n\n\nclass ProfileStore:",
        "profile resolver",
    )

    replace_exact(
        Path("src/openakita/api/routes/execution_instances.py"),
        "    from openakita.agents.profile import get_profile_store\n\n    if not get_profile_store().exists(profile_id):\n        raise HTTPException(status_code=404, detail=\"Agent profile not found\")\n",
        "    from openakita.agents.profile import agent_profile_exists\n\n    if not agent_profile_exists(profile_id):\n        raise HTTPException(status_code=404, detail=\"Agent profile not found\")\n",
        "execution profile validation",
    )

    replace_exact(
        Path("src/openakita/api/routes/hermes.py"),
        "def _require_agent_profile(profile_id: str) -> None:\n    from openakita.agents.profile import get_profile_store\n\n    if not get_profile_store().exists(profile_id):\n        raise HTTPException(status_code=404, detail=\"Agent profile not found\")\n",
        "def _require_agent_profile(profile_id: str) -> None:\n    from openakita.agents.profile import agent_profile_exists\n\n    if not agent_profile_exists(profile_id):\n        raise HTTPException(status_code=404, detail=\"Agent profile not found\")\n",
        "Hermes profile validation",
    )

    path = Path("src/openakita/api/routes/windows_connector.py")
    replace_exact(
        path,
        "@router.post(\"/grants\")\nasync def save_grant(body: GrantPayload) -> dict[str, Any]:\n    try:\n        grant = await windows_connector_manager.upsert_grant(body.model_dump())\n",
        "@router.post(\"/grants\")\nasync def save_grant(body: GrantPayload) -> dict[str, Any]:\n    from openakita.agents.profile import agent_profile_exists\n\n    if not agent_profile_exists(body.agent_profile_id):\n        raise HTTPException(status_code=404, detail=\"Agent profile not found\")\n    try:\n        grant = await windows_connector_manager.upsert_grant(body.model_dump())\n",
        "Windows grant",
    )
    replace_exact(
        path,
        "@router.post(\"/execute\")\nasync def execute(body: ExecutePayload) -> dict[str, Any]:\n    try:\n        return await windows_connector_manager.execute(\n",
        "@router.post(\"/execute\")\nasync def execute(body: ExecutePayload) -> dict[str, Any]:\n    from openakita.agents.profile import agent_profile_exists\n\n    if not agent_profile_exists(body.agent_profile_id):\n        raise HTTPException(status_code=404, detail=\"Agent profile not found\")\n    try:\n        return await windows_connector_manager.execute(\n",
        "Windows execute",
    )

    replace_exact(
        Path("src/openakita/api/routes/llm_gateway.py"),
        "    try:\n        from openakita.agents.profile import get_profile_store\n\n        return get_profile_store().get(profile_id)\n    except Exception:\n        return None\n",
        "    try:\n        from openakita.agents.profile import resolve_agent_profile\n\n        return resolve_agent_profile(profile_id)\n    except Exception:\n        return None\n",
        "Gateway profile fallback",
    )

    path = Path("src/openakita/api/routes/agents.py")
    replace_exact(
        path,
        "    if not isinstance(body.credentials, dict):\n        raise HTTPException(status_code=400, detail=\"credentials must be a dict\")\n\n    existing_ids = {b.get(\"id\") for b in settings.im_bots if isinstance(b, dict)}\n",
        "    if not isinstance(body.credentials, dict):\n        raise HTTPException(status_code=400, detail=\"credentials must be a dict\")\n    from openakita.agents.profile import agent_profile_exists\n\n    if not agent_profile_exists(body.agent_profile_id):\n        raise HTTPException(status_code=404, detail=\"Agent profile not found\")\n\n    existing_ids = {b.get(\"id\") for b in settings.im_bots if isinstance(b, dict)}\n",
        "Bot create validation",
    )
    replace_exact(
        path,
        "    if body.agent_profile_id is not None:\n        bot[\"agent_profile_id\"] = body.agent_profile_id\n",
        "    if body.agent_profile_id is not None:\n        from openakita.agents.profile import agent_profile_exists\n\n        if not agent_profile_exists(body.agent_profile_id):\n            raise HTTPException(status_code=404, detail=\"Agent profile not found\")\n        bot[\"agent_profile_id\"] = body.agent_profile_id\n",
        "Bot update validation",
    )
    replace_exact(
        path,
        "    store = get_profile_store()\n\n    try:\n        deleted = store.delete(profile_id)\n",
        "    store = get_profile_store()\n\n    from openakita.config import settings\n\n    referencing_bots = [\n        str(bot.get(\"id\") or \"\")\n        for bot in settings.im_bots\n        if isinstance(bot, dict)\n        and str(bot.get(\"agent_profile_id\") or \"default\") == profile_id\n    ]\n    if referencing_bots:\n        raise HTTPException(\n            status_code=409,\n            detail=\"Agent is still used by bots: \" + \", \".join(sorted(referencing_bots)),\n        )\n\n    try:\n        deleted = store.delete(profile_id)\n",
        "Profile delete preflight",
    )
    replace_exact(
        path,
        "    finally:\n        execution_store.delete(profile_id)\n        binding_store.delete(profile_id)\n\n    logger.info(f\"[Agents API] Deleted profile: {profile_id}\")\n",
        "    finally:\n        execution_store.delete(profile_id)\n        binding_store.delete(profile_id)\n\n    from openakita.windows_connector import windows_connector_manager\n\n    for grant in await windows_connector_manager.list_grants():\n        if str(grant.get(\"agent_profile_id\") or \"\") != profile_id:\n            continue\n        grant_id = str(grant.get(\"id\") or \"\")\n        if not grant_id:\n            continue\n        try:\n            await windows_connector_manager.delete_grant(grant_id)\n        except Exception as exc:\n            logger.warning(\n                \"[Agents API] Windows grant cleanup failed for %s/%s: %s\",\n                profile_id,\n                grant_id,\n                exc,\n            )\n\n    logger.info(f\"[Agents API] Deleted profile: {profile_id}\")\n",
        "Profile delete cleanup",
    )

    Path("tests/agent/test_profile_reference_integrity.py").write_text(
        "from pathlib import Path\n\n"
        "from openakita.agents import profile as profile_module\n"
        "from openakita.agents.profile import ProfileStore\n\n\n"
        "def test_system_preset_is_resolved_even_when_not_persisted(tmp_path: Path, monkeypatch):\n"
        "    store = ProfileStore(tmp_path / 'agents')\n"
        "    monkeypatch.setattr(profile_module, '_global_store', store)\n"
        "    assert not store.exists('default')\n"
        "    resolved = profile_module.resolve_agent_profile('default')\n"
        "    assert resolved is not None\n"
        "    assert resolved.id == 'default'\n"
        "    assert profile_module.agent_profile_exists('default')\n"
        "    assert not profile_module.agent_profile_exists('definitely-missing-agent')\n",
        "utf-8",
    )


if __name__ == "__main__":
    main()
