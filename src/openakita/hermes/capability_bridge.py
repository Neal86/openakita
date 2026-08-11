"""OpenAkita <-> embedded Hermes capability bridge.

The OpenAkita Agent profile remains the source of truth for durable capability
selection. Hermes is only a runtime: it receives the capabilities enabled for
the current profile and executes bridged OpenAkita tools through the existing
ToolExecutor, preserving permission/risk/MCP/todo enforcement.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class HermesCapabilitySnapshot:
    profile_id: str
    toolset_name: str
    tool_schemas: list[dict[str, Any]] = field(default_factory=list)
    skill_ids: list[str] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    system_context: str = ""

    def metadata(self) -> dict[str, Any]:
        return {
            "capability_bridge": "openakita",
            "profile_id": self.profile_id,
            "skill_ids": list(self.skill_ids),
            "tool_names": list(self.tool_names),
            "mcp_servers": list(self.mcp_servers),
        }


def _safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", value or "default").strip("_")
    return value[:64] or "default"


def _mode_allows(value: str, selected: list[str], mode: str) -> bool:
    selected_set = {str(item).strip() for item in selected if str(item).strip()}
    normalized = (mode or "all").strip().lower()
    if normalized == "inclusive":
        return value in selected_set
    if normalized == "exclusive":
        return value not in selected_set
    return True


def _tool_allowed(profile: Any, *, tool_name: str, category: str = "") -> bool:
    selected = list(getattr(profile, "tools", []) or [])
    mode = str(getattr(profile, "tools_mode", "all") or "all")
    if mode == "all":
        return True
    candidates = {tool_name}
    if category:
        candidates.add(category)
    selected_set = {str(item).strip() for item in selected if str(item).strip()}
    if mode == "inclusive":
        return bool(candidates & selected_set)
    if mode == "exclusive":
        return not bool(candidates & selected_set)
    return True


def _mcp_server_allowed(profile: Any, server: str) -> bool:
    return _mode_allows(
        str(server or ""),
        list(getattr(profile, "mcp_servers", []) or []),
        str(getattr(profile, "mcp_mode", "all") or "all"),
    )


def _to_hermes_schema(schema: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize OpenAkita/Anthropic/OpenAI style tool schemas for Hermes."""
    if not isinstance(schema, dict):
        return None
    if schema.get("type") == "function" and isinstance(schema.get("function"), dict):
        fn = dict(schema["function"])
        name = str(fn.get("name") or "").strip()
        if not name:
            return None
        return {
            "name": name,
            "description": str(fn.get("description") or ""),
            "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
        }
    name = str(schema.get("name") or "").strip()
    if not name:
        return None
    return {
        "name": name,
        "description": str(schema.get("description") or ""),
        "parameters": schema.get("parameters")
        or schema.get("input_schema")
        or {"type": "object", "properties": {}},
    }


def _selected_skill_entries(profile: Any) -> list[Any]:
    try:
        from openakita.skills.registry import default_registry
    except Exception:
        return []

    mode_obj = getattr(profile, "skills_mode", "all")
    mode = str(getattr(mode_obj, "value", mode_obj) or "all")
    selected = list(getattr(profile, "skills", []) or [])
    result: list[Any] = []
    for entry in list(default_registry):
        if getattr(entry, "disabled", False):
            continue
        skill_id = str(getattr(entry, "skill_id", "") or "")
        if not _mode_allows(skill_id, selected, mode):
            continue
        result.append(entry)
    return result


def resolve_capabilities(
    profile_id: str,
    *,
    explicit_tools: list[dict[str, Any]] | None = None,
) -> HermesCapabilitySnapshot:
    """Resolve the durable OpenAkita capability view for one Agent profile."""
    from openakita.agents.profile import get_profile_store

    profile = get_profile_store().get(profile_id)
    toolset_name = f"openakita-{_safe_name(profile_id)}"
    if profile is None:
        return HermesCapabilitySnapshot(profile_id=profile_id, toolset_name=toolset_name)

    tool_schemas: dict[str, dict[str, Any]] = {}
    selected_skill_ids: list[str] = []
    instruction_blocks: list[str] = []

    # Explicit schemas supplied by the Agent call site have the highest
    # fidelity (they can include dynamically discovered MCP/plugin tools).
    for raw in explicit_tools or []:
        normalized = _to_hermes_schema(raw)
        if not normalized:
            continue
        name = str(normalized["name"])
        if _tool_allowed(profile, tool_name=name):
            tool_schemas[name] = normalized

    # The global SkillRegistry is the shared pool. AgentProfile only stores
    # selection policy; switching runtime therefore never copies/moves skills.
    for entry in _selected_skill_entries(profile):
        skill_id = str(getattr(entry, "skill_id", "") or "")
        if skill_id:
            selected_skill_ids.append(skill_id)
        if getattr(entry, "system", False):
            raw_schema = entry.to_tool_schema()
            normalized = _to_hermes_schema(raw_schema)
            if not normalized:
                continue
            name = str(normalized["name"])
            if _tool_allowed(
                profile,
                tool_name=name,
                category=str(getattr(entry, "category", "") or ""),
            ):
                tool_schemas.setdefault(name, normalized)
        else:
            # External Agent Skills are instruction assets rather than a second
            # executable runtime. Feed their instructions to Hermes while tool
            # execution continues through OpenAkita/Hermes native tools.
            body = ""
            try:
                body = str(entry.get_body() or "").strip()
            except Exception:
                body = ""
            if body:
                instruction_blocks.append(
                    f"### OpenAkita Skill: {getattr(entry, 'name', skill_id)}\n{body}"
                )

    selected_mcp = [
        str(item)
        for item in (getattr(profile, "mcp_servers", []) or [])
        if str(item).strip()
    ]
    mcp_mode = str(getattr(profile, "mcp_mode", "all") or "all")

    context_parts = [
        "[OpenAkita Capability Bridge]",
        f"Agent profile: {profile_id}",
        "OpenAkita is the source of truth for durable Skills, Tools, MCP, Memory and Tasks.",
        "Use bridged OpenAkita tools when you need those durable assets; do not create a separate persistent copy inside Hermes.",
    ]
    custom_prompt = str(getattr(profile, "custom_prompt", "") or "").strip()
    if custom_prompt:
        context_parts.append(f"Agent instructions:\n{custom_prompt}")
    if selected_mcp or mcp_mode != "all":
        context_parts.append(
            f"MCP policy: mode={mcp_mode}; selected servers={selected_mcp or 'all'}"
        )
    if instruction_blocks:
        context_parts.append("\n\n".join(instruction_blocks))

    return HermesCapabilitySnapshot(
        profile_id=profile_id,
        toolset_name=toolset_name,
        tool_schemas=list(tool_schemas.values()),
        skill_ids=sorted(set(selected_skill_ids)),
        tool_names=sorted(tool_schemas),
        mcp_servers=selected_mcp,
        system_context="\n\n".join(context_parts),
    )


async def _execute_openakita_tool(
    profile_id: str,
    tool_name: str,
    args: dict[str, Any],
    *,
    session_id: str = "",
) -> str:
    """Execute via OpenAkita's existing ToolExecutor whenever possible."""
    from openakita.agents.profile import get_profile_store

    profile = get_profile_store().get(profile_id)
    if profile is None:
        return json.dumps({"error": f"Unknown Agent profile: {profile_id}"}, ensure_ascii=False)

    if tool_name == "call_mcp_tool":
        server = str(args.get("server") or args.get("server_name") or "")
        if server and not _mcp_server_allowed(profile, server):
            return json.dumps(
                {"error": f"MCP server '{server}' is not enabled for Agent '{profile_id}'"},
                ensure_ascii=False,
            )

    try:
        from openakita.agent.core import get_primary_agent

        agent = get_primary_agent()
    except Exception:
        agent = None

    if agent is not None and getattr(agent, "tool_executor", None) is not None:
        result, _hint = await agent.tool_executor.execute_tool(
            tool_name,
            args,
            session_id=session_id or None,
        )
    else:
        # Startup/test fallback. Production Desktop normally has a primary
        # Agent and therefore uses the full ToolExecutor safety chain above.
        from openakita.tools.handlers import default_handler_registry

        result = await default_handler_registry.execute_by_tool(tool_name, args)

    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception:
        return str(result)


def register_snapshot_with_hermes(
    snapshot: HermesCapabilitySnapshot,
    *,
    session_id: str = "",
) -> str:
    """Register selected OpenAkita tools into Hermes' central registry.

    Hermes' registry is process-global. Registrations are idempotent and use
    ``override=True`` so a profile refresh can replace a stale proxy handler.
    The toolset name is profile-scoped, while the underlying durable tool pool
    remains global in OpenAkita.
    """
    if not snapshot.tool_schemas:
        return snapshot.toolset_name

    try:
        from tools.registry import registry as hermes_registry
    except Exception as exc:  # pragma: no cover - depends on embedded package
        logger.warning("Hermes tool registry unavailable for capability bridge: %s", exc)
        return snapshot.toolset_name

    for schema in snapshot.tool_schemas:
        name = str(schema.get("name") or "").strip()
        if not name:
            continue

        async def _handler(args: dict[str, Any], _tool_name: str = name, **_kwargs: Any) -> str:
            return await _execute_openakita_tool(
                snapshot.profile_id,
                _tool_name,
                args or {},
                session_id=session_id,
            )

        try:
            hermes_registry.register(
                name=name,
                toolset=snapshot.toolset_name,
                schema=schema,
                handler=_handler,
                check_fn=lambda: True,
                is_async=True,
                description=str(schema.get("description") or ""),
                override=True,
            )
        except TypeError:
            # Compatibility with Hermes registry revisions that do not expose
            # ``override``/``description`` kwargs yet.
            try:
                hermes_registry.register(
                    name=name,
                    toolset=snapshot.toolset_name,
                    schema=schema,
                    handler=_handler,
                    check_fn=lambda: True,
                    is_async=True,
                )
            except Exception as exc:
                logger.warning("Failed to register bridged Hermes tool %s: %s", name, exc)
        except Exception as exc:
            logger.warning("Failed to register bridged Hermes tool %s: %s", name, exc)

    return snapshot.toolset_name


def prepare_native_hermes_capabilities(
    profile_id: str,
    *,
    session_id: str = "",
    explicit_tools: list[dict[str, Any]] | None = None,
) -> HermesCapabilitySnapshot:
    snapshot = resolve_capabilities(profile_id, explicit_tools=explicit_tools)
    register_snapshot_with_hermes(snapshot, session_id=session_id)
    return snapshot
