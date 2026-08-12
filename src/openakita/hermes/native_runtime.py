"""Embedded Hermes Agent runtime for OpenAkita Desktop.

OpenAkita remains the durable source of truth for Agent identity, memory,
skills, MCP and tools. Hermes is an execution runtime only.
"""
from __future__ import annotations

import asyncio
import importlib.metadata
import importlib.util
import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from .capability_bridge import prepare_native_hermes_capabilities
from .internal_auth import internal_gateway_secret


class NativeHermesUnavailable(RuntimeError):
    """The embedded Hermes runtime is not present in this build."""


class NativeHermesExecutionError(RuntimeError):
    """Hermes is installed, but the current execution failed."""


class NativeHermesRuntime:
    """Async wrapper around Hermes' synchronous ``AIAgent`` API."""

    _session_locks: dict[str, asyncio.Lock] = {}
    _session_refs: dict[str, int] = {}
    _session_locks_guard = threading.Lock()

    @staticmethod
    def available() -> bool:
        """Report package presence without hiding import-time dependency errors."""
        try:
            return importlib.util.find_spec("run_agent") is not None
        except (ImportError, AttributeError, ValueError):
            return False

    @staticmethod
    def version() -> str:
        try:
            return importlib.metadata.version("hermes-agent")
        except importlib.metadata.PackageNotFoundError:
            return "unavailable"

    @staticmethod
    def _scoped_session_id(agent_id: str, session_id: str) -> str:
        raw_agent = (agent_id or "default").strip() or "default"
        raw_session = (session_id or "default").strip() or "default"
        return f"openakita:{raw_agent}:{raw_session}"

    @classmethod
    @asynccontextmanager
    async def _session_guard(cls, scoped_session: str):
        """Serialize one Hermes session and reclaim idle lock objects."""
        with cls._session_locks_guard:
            lock = cls._session_locks.get(scoped_session)
            if lock is None:
                lock = asyncio.Lock()
                cls._session_locks[scoped_session] = lock
            cls._session_refs[scoped_session] = cls._session_refs.get(scoped_session, 0) + 1
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()
            with cls._session_locks_guard:
                refs = max(0, cls._session_refs.get(scoped_session, 1) - 1)
                if refs:
                    cls._session_refs[scoped_session] = refs
                else:
                    cls._session_refs.pop(scoped_session, None)
                    if not lock.locked():
                        cls._session_locks.pop(scoped_session, None)

    @classmethod
    def _agent_kwargs(cls, *, agent_id: str, session_id: str, stream_delta_callback=None) -> dict[str, Any]:
        base_url = os.environ.get(
            "OPENAKITA_HERMES_LLM_BASE_URL",
            os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:18900/v1"),
        ).rstrip("/")
        kwargs: dict[str, Any] = {
            "base_url": base_url,
            "api_key": internal_gateway_secret(),
            "provider": os.environ.get("OPENAKITA_HERMES_PROVIDER", "custom"),
            "model": os.environ.get("OPENAKITA_HERMES_MODEL", f"agent:{agent_id}"),
            "api_mode": "chat_completions",
            "quiet_mode": True,
            "save_trajectories": False,
            "platform": "openakita-desktop",
            "session_id": cls._scoped_session_id(agent_id, session_id),
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
        except ModuleNotFoundError as exc:  # pragma: no cover - bundled dependency
            raise NativeHermesUnavailable(
                "Embedded Hermes runtime is not installed in this OpenAkita build"
            ) from exc
        except Exception as exc:  # package exists but cannot initialize
            raise NativeHermesExecutionError(
                f"Embedded Hermes runtime failed to initialize: {exc}"
            ) from exc
        try:
            return AIAgent(
                **cls._agent_kwargs(
                    agent_id=agent_id,
                    session_id=session_id,
                    stream_delta_callback=stream_delta_callback,
                )
            )
        except Exception as exc:
            raise NativeHermesExecutionError(f"Unable to create Hermes Agent: {exc}") from exc

    @staticmethod
    def _merged_system(system: str, bridge_context: str) -> str:
        return "\n\n".join(part.strip() for part in (system, bridge_context) if part and part.strip())

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
        async with cls._session_guard(scoped_session):
            snapshot = prepare_native_hermes_capabilities(
                agent_id,
                session_id=scoped_session,
                explicit_tools=tools,
            )
            effective_system = cls._merged_system(system, snapshot.system_context)

            def _execute() -> dict[str, Any]:
                agent = cls._new_agent(agent_id=agent_id, session_id=session_id)
                try:
                    result = agent.run_conversation(
                        user_message=message,
                        system_message=effective_system or None,
                        task_id=scoped_session,
                    )
                except (NativeHermesUnavailable, NativeHermesExecutionError):
                    raise
                except Exception as exc:
                    raise NativeHermesExecutionError(f"Hermes conversation failed: {exc}") from exc
                return result if isinstance(result, dict) else {"final_response": str(result)}

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
        scoped_session = cls._scoped_session_id(agent_id, session_id)
        async with cls._session_guard(scoped_session):
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
            snapshot = prepare_native_hermes_capabilities(
                agent_id,
                session_id=scoped_session,
                explicit_tools=tools,
            )
            effective_system = cls._merged_system(system, snapshot.system_context)
            emitted_delta = threading.Event()

            def _on_delta(delta: Any) -> None:
                if isinstance(delta, str):
                    text = delta
                elif isinstance(delta, dict):
                    text = str(delta.get("content") or delta.get("delta") or "")
                else:
                    text = str(delta or "")
                if text:
                    emitted_delta.set()
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
                    try:
                        result = agent.run_conversation(
                            user_message=message,
                            system_message=effective_system or None,
                            task_id=scoped_session,
                        )
                    except Exception as exc:
                        raise NativeHermesExecutionError(f"Hermes conversation failed: {exc}") from exc
                    final = result.get("final_response") if isinstance(result, dict) else str(result)
                    if final and not emitted_delta.is_set():
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            {"type": "final", "content": str(final), "runtime": "native"},
                        )
                except NativeHermesUnavailable as exc:
                    loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "error_kind": "unavailable", "error": str(exc), "runtime": "native"})
                except Exception as exc:
                    loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "error_kind": "execution", "error": str(exc), "runtime": "native"})
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)

            worker_task = asyncio.create_task(asyncio.to_thread(_worker))
            cancelled: asyncio.CancelledError | None = None
            try:
                while True:
                    event = await queue.get()
                    if event is None:
                        break
                    if event.get("type") == "error":
                        message_text = str(event.get("error") or "Hermes native runtime failed")
                        if event.get("error_kind") == "unavailable":
                            raise NativeHermesUnavailable(message_text)
                        raise NativeHermesExecutionError(message_text)
                    yield event
                await worker_task
                yield {
                    "type": "done",
                    "runtime": "native",
                    "hermes_version": cls.version(),
                    "agent_profile_id": agent_id,
                    "hermes_session_id": scoped_session,
                    **snapshot.metadata(),
                    **(metadata or {}),
                }
            except asyncio.CancelledError as exc:
                cancelled = exc
            finally:
                # Cancelling asyncio.to_thread does not stop its Python thread. Keep
                # the session guard held until the worker really exits so a second
                # request cannot overlap the same Hermes session.
                if not worker_task.done():
                    try:
                        await asyncio.shield(worker_task)
                    except asyncio.CancelledError:
                        await worker_task
                if cancelled is not None:
                    raise cancelled
