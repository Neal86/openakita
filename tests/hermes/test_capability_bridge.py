from __future__ import annotations

from types import SimpleNamespace

import pytest

from openakita.hermes import capability_bridge as bridge


def _profile(**overrides):
    base = {
        "skills": [],
        "skills_mode": "all",
        "tools": [],
        "tools_mode": "all",
        "mcp_servers": [],
        "mcp_mode": "all",
        "custom_prompt": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_profile_scoped_proxy_names_do_not_collide() -> None:
    a = bridge._bridge_tool_name("sales", "call_mcp_tool")
    b = bridge._bridge_tool_name("support", "call_mcp_tool")
    assert a != b
    assert a.startswith("oa_") and b.startswith("oa_")
    assert len(a) <= 63 and len(b) <= 63
    assert a == bridge._bridge_tool_name("sales", "call_mcp_tool")


def test_resolve_capabilities_filters_and_namespaces_explicit_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = _profile(tools=["list_files"], tools_mode="inclusive")
    monkeypatch.setattr(bridge, "_profile", lambda _profile_id: profile)
    monkeypatch.setattr(bridge, "_selected_skill_entries", lambda _profile: [])

    tools = [
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List files",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_file",
                "description": "Delete",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]
    snapshot = bridge.resolve_capabilities("support", explicit_tools=tools)

    assert snapshot.tool_names == ["list_files"]
    assert len(snapshot.tool_schemas) == 1
    proxy_name = snapshot.tool_schemas[0]["name"]
    assert proxy_name != "list_files"
    assert snapshot.tool_name_map[proxy_name] == "list_files"
    assert "delete_file" not in snapshot.tool_names


def test_mcp_policy_is_agent_scoped() -> None:
    profile = _profile(mcp_servers=["allowed"], mcp_mode="inclusive")
    assert bridge._mcp_server_allowed(profile, "allowed") is True
    assert bridge._mcp_server_allowed(profile, "other") is False


@pytest.mark.asyncio
async def test_execute_rejects_mcp_server_outside_profile_before_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = _profile(mcp_servers=["allowed"], mcp_mode="inclusive")
    monkeypatch.setattr(bridge, "_profile", lambda _profile_id: profile)

    result = await bridge._execute_openakita_tool(
        "support",
        "call_mcp_tool",
        {"server": "other", "tool_name": "anything", "arguments": {}},
    )
    assert "not enabled" in result
    assert "other" in result


def test_openai_and_openakita_tool_schema_normalization() -> None:
    openai_schema = {
        "type": "function",
        "function": {
            "name": "alpha",
            "description": "A",
            "parameters": {"type": "object", "properties": {"x": {"type": "string"}}},
        },
    }
    openakita_schema = {
        "name": "beta",
        "description": "B",
        "input_schema": {"type": "object", "properties": {}},
    }
    assert bridge._to_hermes_schema(openai_schema)["name"] == "alpha"
    assert bridge._to_hermes_schema(openakita_schema)["name"] == "beta"
