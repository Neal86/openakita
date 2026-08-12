"""OpenAkita <-> embedded Hermes capability bridge.

OpenAkita remains the source of truth for durable Agent capabilities. Hermes
receives a profile-filtered view and executes OpenAkita tools through the
existing ToolExecutor so risk/permission/MCP/todo enforcement is preserved.

Hermes' tool registry is process-global, therefore every bridge proxy uses a
stable profile-scoped function name. This prevents two simultaneously active
Agents from overwriting each other's proxy handlers or capability selection.
"""
from __future__ import annotations

import hashlib
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
    tool_name_map: dict[str, str] = field(default_factory=dict)
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
            "tool_name_map": dict(self.tool_name_map),
        }


def _safe_name(value: str, limit: int = 40) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", value or "default").strip("_")
    return value[:limit] or "default"


def _profile_key(profile_id: str) -> str:
    readable = _safe_name(profile_id, 18)
    digest = hashlib.blake2s((profile_id or "default").encode("utf-8"), digest_size=4).hexdigest()
    return f"{readable}_{digest}"


def _bridge_tool_name(profile_id: str, original_name: str) -> str:
    prefix = f"oa_{_profile_key(profile_id)}__"
    remaining = max(8, 63 - len(prefix))
    return prefix + _safe_name(original_name, remaining)


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
        if _mode_allows(skill_id, selected, mode):
            result.append(entry)
    return result


def _profile(profile_id: str) -> Any | None:
    from openakita.agents.profile import get_profile_store

    return get_profile_store().get(profile_id)


def _known_skill_ids() -> set[str]:
    try:
        from openakita.skills.registry import default_registry

        return {
            str(getattr(entry, "skill_id", "") or "")
            for entry in list(default_registry)
            if str(getattr(entry, "skill_id", "") or "")
        }
    except Exception:
        return set()


def _persist_profile_enablement(
    profile_id: str,
    *,
    skill_ids: set[str] | None = None,
    mcp_server: str = "",
) -> None:
    """Make newly-created durable assets immediately usable by their creator.

    `all` needs no relation update. In `inclusive` mode we append the new asset;
    in `exclusive` mode we remove it from exclusions. This preserves the user's
    chosen selection semantics instead of silently converting the profile mode.
    """
    try:
        from openakita.agents.profile import get_profile_store

        store = get_profile_store()
        profile = store.get(profile_id)
        if profile is None:
            return
        changed = False

        if skill_ids:
            mode_obj = getattr(profile, "skills_mode", "all")
            mode = str(getattr(mode_obj, "value", mode_obj) or "all")
            current = list(getattr(profile, "skills", []) or [])
            if mode == "inclusive":
                for skill_id in sorted(skill_ids):
                    if skill_id not in current:
                        current.append(skill_id)
                        changed = True
            elif mode == "exclusive":
                reduced = [sid for sid in current if sid not in skill_ids]
                if reduced != current:
                    current = reduced
                    changed = True
            if changed:
                profile.skills = current

        if mcp_server:
            mode = str(getattr(profile, "mcp_mode", "all") or "all")
            current_mcp = list(getattr(profile, "mcp_servers", []) or [])
            if mode == "inclusive" and mcp_server not in current_mcp:
                current_mcp.append(mcp_server)
                profile.mcp_servers = current_mcp
                changed = True
            elif mode == "exclusive" and mcp_server in current_mcp:
                profile.mcp_servers = [sid for sid in current_mcp if sid != mcp_server]
                changed = True

        if changed:
            store.save(profile)
            logger.info(
                "Hermes capability bridge updated Agent enablement: profile=%s skills=%s mcp=%s",
                profile_id,
                sorted(skill_ids or set()),
                mcp_server or "-",
            )
    except Exception:
        logger.warning("Failed to persist Hermes-created capability enablement", exc_info=True)


def resolve_capabilities(
    profile_id: str,
    *,
    explicit_tools: list[dict[str, Any]] | None = None,
) -> HermesCapabilitySnapshot:
    profile = _profile(profile_id)
    toolset_name = f"openakita-{_profile_key(profile_id)}"
    if profile is None:
        return HermesCapabilitySnapshot(profile_id=profile_id, toolset_name=toolset_name)

    original_schemas: dict[str, dict[str, Any]] = {}
    selected_skill_ids: list[str] = []
    instruction_blocks: list[str] = []

    # Windows Connector tools are global capabilities; per-Agent app grants are
    # enforced again by the handler/connector and do not create private tool copies.
    try:
        from openakita.windows_connector.tools import WINDOWS_CONNECTOR_TOOLS
    except Exception:
        WINDOWS_CONNECTOR_TOOLS = []
    for raw in WINDOWS_CONNECTOR_TOOLS:
        normalized = _to_hermes_schema(raw)
        if not normalized:
            continue
        original = str(normalized["name"])
        if _tool_allowed(profile, tool_name=original, category="Windows Connector"):
            original_schemas[original] = normalized

    for raw in explicit_tools or []:
        normalized = _to_hermes_schema(raw)
        if not normalized:
            continue
        original = str(normalized["name"])
        if _tool_allowed(profile, tool_name=original):
            original_schemas[original] = normalized

    for entry in _selected_skill_entries(profile):
        skill_id = str(getattr(entry, "skill_id", "") or "")
        if skill_id:
            selected_skill_ids.append(skill_id)
        if getattr(entry, "system", False):
            normalized = _to_hermes_schema(entry.to_tool_schema())
            if not normalized:
                continue
            original = str(normalized["name"])
            if _tool_allowed(
                profile,
                tool_name=original,
                category=str(getattr(entry, "category", "") or ""),
            ):
                original_schemas.setdefault(original, normalized)
        else:
            try:
                body = str(entry.get_body() or "").strip()
            except Exception:
                body = ""
            if body:
                instruction_blocks.append(
                    f"### OpenAkita Skill: {getattr(entry, 'name', skill_id)}\n{body}"
                )

    tool_schemas: list[dict[str, Any]] = []
    tool_name_map: dict[str, str] = {}
    for original, schema in original_schemas.items():
        bridged = _bridge_tool_name(profile_id, original)
        proxy = dict(schema)
        proxy["name"] = bridged
        proxy["description"] = (
            f"[OpenAkita tool: {original}] " + str(schema.get("description") or "")
        ).strip()
        tool_schemas.append(proxy)
        tool_name_map[bridged] = original

    selected_mcp = [str(item) for item in (getattr(profile, "mcp_servers", []) or []) if str(item).strip()]
    mcp_mode = str(getattr(profile, "mcp_mode", "all") or "all")
    context_parts = [
        "[OpenAkita Capability Bridge]",
        f"Agent profile: {profile_id}",
        "OpenAkita is the source of truth for durable Skills, Tools, MCP, Memory, Identity and Tasks.",
        "Use oa_* bridged functions for durable OpenAkita capabilities; descriptions contain original tool names.",
        "When creating a reusable Skill, write it into OpenAkita's skills directory and use the bridged load_skill/reload_skill tools. When adding MCP, use the bridged add_mcp_server tool. Do not create a second persistent copy inside Hermes.",
    ]
    custom_prompt = str(getattr(profile, "custom_prompt", "") or "").strip()
    if custom_prompt:
        context_parts.append(f"Agent instructions:\n{custom_prompt}")
    if selected_mcp or mcp_mode != "all":
        context_parts.append(f"MCP policy: mode={mcp_mode}; selected servers={selected_mcp or 'all'}")
    if instruction_blocks:
        context_parts.append("\n\n".join(instruction_blocks))

    return HermesCapabilitySnapshot(
        profile_id=profile_id,
        toolset_name=toolset_name,
        tool_schemas=tool_schemas,
        tool_name_map=tool_name_map,
        skill_ids=sorted(set(selected_skill_ids)),
        tool_names=sorted(original_schemas),
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
    profile = _profile(profile_id)
    if profile is None:
        return json.dumps({"error": f"Unknown Agent profile: {profile_id}"}, ensure_ascii=False)
    if not _tool_allowed(profile, tool_name=tool_name):
        return json.dumps({"error": f"Tool '{tool_name}' is not enabled for Agent '{profile_id}'"}, ensure_ascii=False)
    if tool_name == "call_mcp_tool":
        server = str(args.get("server") or args.get("server_name") or "")
        if server and not _mcp_server_allowed(profile, server):
            return json.dumps({"error": f"MCP server '{server}' is not enabled for Agent '{profile_id}'"}, ensure_ascii=False)

    before_skills = _known_skill_ids() if tool_name in {"install_skill", "load_skill", "reload_skill"} else set()
    try:
        from openakita.agent.core import get_primary_agent

        agent = get_primary_agent()
    except Exception:
        agent = None

    from openakita.windows_connector.context import current_agent_profile_id
    profile_token = current_agent_profile_id.set(profile_id)
    try:
        if agent is not None and getattr(agent, "tool_executor", None) is not None:
            result, _hint = await agent.tool_executor.execute_tool(tool_name, args, session_id=session_id or None)
        else:
            from openakita.tools.handlers import default_handler_registry

            result = await default_handler_registry.execute_by_tool(tool_name, args)
    finally:
        current_agent_profile_id.reset(profile_token)

    result_text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    # Only persist relationships after a successful-looking control-plane operation.
    if not result_text.lstrip().startswith("❌"):
        if tool_name in {"install_skill", "load_skill", "reload_skill"}:
            new_skills = _known_skill_ids() - before_skills
            explicit_skill = str(args.get("skill_name") or args.get("name") or "").strip()
            if explicit_skill and explicit_skill in _known_skill_ids():
                new_skills.add(explicit_skill)
            _persist_profile_enablement(profile_id, skill_ids=new_skills)
        elif tool_name == "add_mcp_server":
            server = str(args.get("name") or "").strip()
            if server:
                _persist_profile_enablement(profile_id, mcp_server=server)
    return result_text


def register_snapshot_with_hermes(snapshot: HermesCapabilitySnapshot, *, session_id: str = "") -> str:
    if not snapshot.tool_schemas:
        return snapshot.toolset_name
    try:
        from tools.registry import registry as hermes_registry
    except Exception as exc:  # pragma: no cover
        logger.warning("Hermes tool registry unavailable for capability bridge: %s", exc)
        return snapshot.toolset_name

    for schema in snapshot.tool_schemas:
        bridged_name = str(schema.get("name") or "").strip()
        original_name = snapshot.tool_name_map.get(bridged_name, "")
        if not bridged_name or not original_name:
            continue

        async def _handler(args: dict[str, Any], _original_name: str = original_name, **_kwargs: Any) -> str:
            return await _execute_openakita_tool(snapshot.profile_id, _original_name, args or {}, session_id=session_id)

        try:
            hermes_registry.register(
                name=bridged_name,
                toolset=snapshot.toolset_name,
                schema=schema,
                handler=_handler,
                check_fn=lambda: True,
                is_async=True,
                description=str(schema.get("description") or ""),
                override=True,
            )
        except TypeError:
            try:
                hermes_registry.register(
                    name=bridged_name,
                    toolset=snapshot.toolset_name,
                    schema=schema,
                    handler=_handler,
                    check_fn=lambda: True,
                    is_async=True,
                )
            except Exception as exc:
                logger.warning("Failed to register bridged Hermes tool %s: %s", bridged_name, exc)
        except Exception as exc:
            logger.warning("Failed to register bridged Hermes tool %s: %s", bridged_name, exc)
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
