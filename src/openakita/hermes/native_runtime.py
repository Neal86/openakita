"""Embedded Hermes Agent runtime for OpenAkita Desktop.

This adapter embeds Nous Research Hermes' ``AIAgent`` in the OpenAkita backend
process. Desktop does not need Docker or a second Hermes gateway process.
Server deployments may still use the existing Docker/HTTP runtime.

Durable identity/capability state remains owned by OpenAkita. Before each
native Hermes session starts, the capability bridge resolves the current Agent
profile and registers the enabled OpenAkita tools into Hermes' central tool
registry. Hermes' own private memory/context files are disabled so switching
runtime never forks the Agent's long-term Memory/Skills/MCP state.
"""
from __future__ import annotations

import asyncio
import importlib.metadata
import os
from collections.abc import AsyncIterator
from typing import Any

from .capability_bridge import prepare_native_hermes_capabilities


class NativeHermesUnavailable(RuntimeError):
    """Raised when the embedded Hermes package is not present in this build."""


class NativeHermesRuntime:
    """Small async wrapper around Hermes' synchronous ``AIAgent`` API."""

    @staticmethod
    def available() -> bool:
        try:
            import run_agent  # noqa: F401

            return True
        except Exception:
            return False

    @staticmethod
    def version() -> str:
        try:
            return importlib.metadata.version("hermes-agent")
        except importlib.metadata.PackageNotFoundError:
            return "unavailable"

    @staticmethod
    def _scoped_session_id(agent_id: str, session_id: str) -> str:
        """Keep Hermes session state isolated across OpenAkita Agent profiles."""
        raw_agent = (agent_id or "default").strip() or "default"
        raw_session = (session_id or "default").strip() or "default"
        return f"openakita:{raw_agent}:{raw_session}"

    @classmethod
    def _agent_kwargs(
        cls,
        *,
        agent_id: str,
        session_id: str,
        stream_delta_callback=None,
    ) -> dict[str, Any]:
        # Hermes talks back to OpenAkita's OpenAI-compatible internal gateway.
        # Provider/model/API-key ownership therefore stays in OpenAkita rather
        # than being duplicated inside every embedded Hermes profile.
        base_url = os.environ.get(
            "OPENAKITA_HERMES_LLM_BASE_URL",
            os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:18900/v1"),
        ).rstrip("/")
        api_key = os.environ.get("OPENAKITA_HERMES_LLM_API_KEY", "openakita-internal")
        model = os.environ.get("OPENAKITA_HERMES_MODEL", f"agent:{agent_id}")
        provider = os.environ.get("OPENAKITA_HERMES_PROVIDER", "custom")
        kwargs: dict[str, Any] = {
            "base_url": base_url,
            "api_key": api_key,
            "provider": provider,
            "model": model,
            "api_mode": "chat_completions",
            "quiet_mode": True,
            "save_trajectories": False,
            "platform": "openakita-desktop",
            "session_id": cls._scoped_session_id(agent_id, session_id),
            # OpenAkita owns durable Agent identity/memory. Hermes keeps its
            # execution loop, subagents and native tools, but must not create a
            # second long-term memory/context universe for the same Agent.
            "skip_memory": True,
            "skip_context_files": True,
        }
        if stream_delta_callback is not None:
            kwargs["stream_delta_callback"] = stream_delta_callback
        return kwargs

    @classmethod
    def _new_agent(cls, *, agent_id: str, session_id: str, stream_delta_callback=None):
        try:
            from run_agent import AIAgent
        except Exception as exc:  # pragma: no cover - depends on bundled package
            raise NativeHermesUnavailable(
                "Embedded Hermes runtime is not installed in this OpenAkita build"
            ) from exc
        return AIAgent(
            **cls._agent_kwargs(
                agent_id=agent_id,
                session_id=session_id,
                stream_delta_callback=stream_delta_callback,
            )
        )

    @staticmethod
    def _merged_system(system: str, bridge_context: str) -> str:
        parts = [part.strip() for part in (system, bridge_context) if part and part.strip()]
        return "\n\n".join(parts)

    @classmethod
    async def run(
        cls,
        *,
        message: str,
        agent_id: str,
        session_id: str = "",
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scoped_session = cls._scoped_session_id(agent_id, session_id)
        snapshot = prepare_native_hermes_capabilities(
            agent_id,
            session_id=scoped_session,
            explicit_tools=tools,
        )
        effective_system = cls._merged_system(system, snapshot.system_context)

        def _execute() -> dict[str, Any]:
            agent = cls._new_agent(agent_id=agent_id, session_id=session_id)
            result = agent.run_conversation(
                user_message=message,
                system_message=effective_system or None,
                task_id=scoped_session,
            )
            if isinstance(result, dict):
                return result
            return {"final_response": str(result)}

        result = await asyncio.to_thread(_execute)
        return {
            "content": str(result.get("final_response") or result.get("content") or ""),
            "usage": result.get("usage") or {},
            "metadata": {
                "runtime": "native",
                "hermes_version": cls.version(),
                "agent_profile_id": agent_id,
                "hermes_session_id": scoped_session,
                **snapshot.metadata(),
                **(metadata or {}),
            },
        }

    @classmethod
    async def run_stream(
        cls,
        *,
        message: str,
        agent_id: str,
        session_id: str = "",
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        scoped_session = cls._scoped_session_id(agent_id, session_id)
        snapshot = prepare_native_hermes_capabilities(
            agent_id,
            session_id=scoped_session,
            explicit_tools=tools,
        )
        effective_system = cls._merged_system(system, snapshot.system_context)

        def _on_delta(delta: Any) -> None:
            text = ""
            if isinstance(delta, str):
                text = delta
            elif isinstance(delta, dict):
                text = str(delta.get("content") or delta.get("delta") or "")
            else:
                text = str(delta or "")
            if text:
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"type": "text_delta", "content": text, "runtime": "native"},
                )

        def _worker() -> None:
            try:
                agent = cls._new_agent(
                    agent_id=agent_id,
                    session_id=session_id,
                    stream_delta_callback=_on_delta,
                )
                result = agent.run_conversation(
                    user_message=message,
                    system_message=effective_system or None,
                    task_id=scoped_session,
                )
                # Some provider modes do not emit delta callbacks. Ensure the
                # caller still receives a final response in those modes.
                final = result.get("final_response") if isinstance(result, dict) else str(result)
                if final:
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        {"type": "final", "content": str(final), "runtime": "native"},
                    )
            except Exception as exc:
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"type": "error", "error": str(exc), "runtime": "native"},
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        task = asyncio.create_task(asyncio.to_thread(_worker))
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                if event.get("type") == "error":
                    raise NativeHermesUnavailable(
                        str(event.get("error") or "Hermes native runtime failed")
                    )
                yield event
            await task
            yield {
                "type": "done",
                "runtime": "native",
                "hermes_version": cls.version(),
                "agent_profile_id": agent_id,
                "hermes_session_id": scoped_session,
                **snapshot.metadata(),
                **(metadata or {}),
            }
        finally:
            if not task.done():
                task.cancel()
