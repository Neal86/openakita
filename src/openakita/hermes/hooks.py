"""Runtime hooks that integrate Hermes with the existing Agent chat surface."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from .bindings import AgentHermesBindingStore
from .models import HermesRuntimeProvider
from .runtime import execute_with_hermes_fallback, stream_with_hermes_fallback

logger = logging.getLogger(__name__)
_INSTALLED = False


def _session_value(session: Any, key: str, default: Any = None) -> Any:
    if session is None:
        return default
    getter = getattr(session, "get_metadata", None)
    if callable(getter):
        try:
            value = getter(key)
            if value is not None:
                return value
        except Exception:
            pass
    metadata = getattr(session, "metadata", None)
    if isinstance(metadata, dict) and key in metadata:
        return metadata[key]
    if isinstance(session, dict):
        nested = session.get("metadata")
        if isinstance(nested, dict) and key in nested:
            return nested[key]
        return session.get(key, default)
    return getattr(session, key, default)


def _extract_call(self: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[str, str, Any]:
    message = kwargs.get("message")
    session = kwargs.get("session")
    if message is None and args:
        message = args[0]
    if session is None:
        for value in args[1:]:
            if hasattr(value, "metadata") or hasattr(value, "get_metadata"):
                session = value
                break
    profile_id = (
        kwargs.get("profile_id")
        or kwargs.get("agent_profile_id")
        or _session_value(session, "agent_profile_id")
        or _session_value(session, "_bot_default_agent")
        or getattr(self, "profile_id", None)
        or getattr(getattr(self, "profile", None), "id", None)
        or "default"
    )
    return str(profile_id), str(message or ""), session


def _runtime_args(profile_id: str, message: str, session: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_id": profile_id,
        "message": message,
        "session_id": str(kwargs.get("session_id") or _session_value(session, "id", "") or ""),
        "system": str(kwargs.get("system") or ""),
        "tools": kwargs.get("tools") or [],
        "metadata": {
            "mode": kwargs.get("mode") or "chat",
            "channel": _session_value(session, "channel", ""),
            "user_id": _session_value(session, "user_id", ""),
        },
    }


def _normalize_remote_event(event: Any) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    normalized = dict(event)
    event_type = str(normalized.get("type") or "")
    if event_type in {"delta", "token", "content_delta"}:
        normalized["type"] = "text_delta"
    elif event_type in {"complete", "completed", "finish"}:
        normalized["type"] = "done"
    if "content" not in normalized and "text" in normalized:
        normalized["content"] = normalized.get("text")
    return normalized


def install_agent_hooks() -> None:
    """Install idempotent Hermes routing wrappers on the canonical Agent class."""
    global _INSTALLED
    if _INSTALLED:
        return

    from openakita.agent.core import Agent

    original_chat = getattr(Agent, "chat_with_session", None)
    original_stream = getattr(Agent, "chat_with_session_stream", None)

    if callable(original_chat) and not getattr(original_chat, "_hermes_wrapped", False):
        async def chat_with_session(self: Any, *args: Any, **kwargs: Any) -> Any:
            profile_id, message, session = _extract_call(self, args, kwargs)
            binding = AgentHermesBindingStore().get(profile_id)
            if binding.runtime_provider == HermesRuntimeProvider.LOCAL:
                return await original_chat(self, *args, **kwargs)

            async def local_runner() -> Any:
                return await original_chat(self, *args, **kwargs)

            result = await execute_with_hermes_fallback(
                **_runtime_args(profile_id, message, session, kwargs),
                local_runner=local_runner,
            )
            content = getattr(result, "content", result)
            return str(content or "")

        chat_with_session._hermes_wrapped = True  # type: ignore[attr-defined]
        chat_with_session._hermes_original = original_chat  # type: ignore[attr-defined]
        Agent.chat_with_session = chat_with_session  # type: ignore[method-assign]

    if callable(original_stream) and not getattr(original_stream, "_hermes_wrapped", False):
        async def chat_with_session_stream(self: Any, *args: Any, **kwargs: Any):
            profile_id, message, session = _extract_call(self, args, kwargs)

            async def local_stream_runner() -> AsyncIterator[dict[str, Any]]:
                async for event in original_stream(self, *args, **kwargs):
                    yield event

            async for event in stream_with_hermes_fallback(
                **_runtime_args(profile_id, message, session, kwargs),
                local_stream_runner=local_stream_runner,
            ):
                normalized = _normalize_remote_event(event)
                if normalized is not None:
                    yield normalized

        chat_with_session_stream._hermes_wrapped = True  # type: ignore[attr-defined]
        chat_with_session_stream._hermes_original = original_stream  # type: ignore[attr-defined]
        Agent.chat_with_session_stream = chat_with_session_stream  # type: ignore[method-assign]

    _INSTALLED = True
    logger.info("Hermes Agent runtime hooks installed")
