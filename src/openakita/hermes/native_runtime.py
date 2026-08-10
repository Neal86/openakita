"""Embedded Hermes Agent runtime for OpenAkita Desktop.

This adapter embeds Nous Research Hermes' ``AIAgent`` in the OpenAkita backend
process.  It is intentionally transport-free: Desktop does not need Docker or a
second Hermes gateway process.  Server deployments may still use the existing
Docker/HTTP runtime.
"""
from __future__ import annotations

import asyncio
import importlib.metadata
import os
from collections.abc import AsyncIterator
from typing import Any


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
    def _agent_kwargs(*, agent_id: str, session_id: str, stream_delta_callback=None) -> dict[str, Any]:
        # Hermes talks back to OpenAkita's OpenAI-compatible internal gateway.
        # That keeps provider/model/API-key ownership in OpenAkita rather than
        # duplicating provider configuration inside every Hermes profile.
        base_url = os.environ.get(
            "OPENAKITA_HERMES_LLM_BASE_URL",
            os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:18900/v1"),
        ).rstrip("/")
        api_key = os.environ.get("OPENAKITA_HERMES_LLM_API_KEY", "openakita-internal")
        model = os.environ.get("OPENAKITA_HERMES_MODEL", f"agent:{agent_id}")
        kwargs: dict[str, Any] = {
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
            "api_mode": "chat_completions",
            "quiet_mode": True,
            "save_trajectories": False,
            "platform": "openakita-desktop",
            "session_id": session_id or None,
        }
        if stream_delta_callback is not None:
            kwargs["stream_delta_callback"] = stream_delta_callback
        return kwargs

    @classmethod
    def _new_agent(cls, *, agent_id: str, session_id: str, stream_delta_callback=None):
        try:
            from run_agent import AIAgent
        except Exception as exc:  # pragma: no cover - depends on optional bundled package
            raise NativeHermesUnavailable(
                "Embedded Hermes runtime is not installed in this OpenAkita build"
            ) from exc
        return AIAgent(**cls._agent_kwargs(
            agent_id=agent_id,
            session_id=session_id,
            stream_delta_callback=stream_delta_callback,
        ))

    @classmethod
    async def run(
        cls,
        *,
        message: str,
        agent_id: str,
        session_id: str = "",
        system: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        def _execute() -> dict[str, Any]:
            agent = cls._new_agent(agent_id=agent_id, session_id=session_id)
            result = agent.run_conversation(
                user_message=message,
                system_message=system or None,
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
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

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
                    system_message=system or None,
                )
                # Some Hermes provider modes do not emit delta callbacks.  In
                # that case make sure callers still receive the final answer.
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
                    raise NativeHermesUnavailable(str(event.get("error") or "Hermes native runtime failed"))
                yield event
            await task
            yield {
                "type": "done",
                "runtime": "native",
                "hermes_version": cls.version(),
                "agent_profile_id": agent_id,
                **(metadata or {}),
            }
        finally:
            if not task.done():
                task.cancel()
