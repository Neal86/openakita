"""Official Hermes Agent OpenAI-compatible HTTP/SSE client."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from .models import HermesNode


@dataclass
class HermesResponse:
    content: str
    node_id: str
    usage: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class HermesClient:
    """Client for Nous Research Hermes Agent's official API server.

    Shared OpenAkita Hermes instances use ``X-OpenAkita-Agent-Id`` to select
    the isolated child process for one Agent profile. Dedicated instances
    accept the same header, so callers do not need separate code paths.
    """

    def __init__(self, node: HermesNode) -> None:
        self.node = node

    def _headers(self, *, session_id: str = "", agent_id: str = "") -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.node.api_key_env:
            key = os.environ.get(self.node.api_key_env, "").strip()
            if key:
                headers["Authorization"] = f"Bearer {key}"
        if session_id:
            headers["X-Hermes-Session-Id"] = session_id
        if agent_id:
            headers["X-OpenAkita-Agent-Id"] = agent_id
        return headers

    @staticmethod
    def _messages(message: str, system: str = "") -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system.strip():
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": message})
        return messages

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=min(self.node.timeout_seconds, 15)) as client:
            response = await client.get(f"{self.node.base_url}/health", headers=self._headers())
            response.raise_for_status()
            try:
                return response.json()
            except ValueError:
                return {"status": response.text or "ok"}

    async def run(
        self,
        *,
        message: str,
        agent_id: str,
        session_id: str = "",
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> HermesResponse:
        payload: dict[str, Any] = {
            "model": f"agent:{agent_id}" if agent_id else "openakita-auto",
            "messages": self._messages(message, system),
            "stream": False,
            "metadata": {"agent_profile_id": agent_id, **(metadata or {})},
        }
        if tools:
            payload["tools"] = tools
        async with httpx.AsyncClient(timeout=self.node.timeout_seconds) as client:
            response = await client.post(
                f"{self.node.base_url}/v1/chat/completions",
                headers=self._headers(session_id=session_id, agent_id=agent_id),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices") or []
        content = ""
        if choices:
            message_obj = choices[0].get("message") or {}
            content = message_obj.get("content") or ""
        return HermesResponse(
            content=str(content),
            node_id=self.node.id,
            usage=data.get("usage") or {},
            metadata={
                "id": data.get("id"),
                "model": data.get("model"),
                "agent_profile_id": agent_id,
                **(metadata or {}),
            },
        )

    async def run_stream(
        self,
        *,
        message: str,
        agent_id: str,
        session_id: str = "",
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        payload: dict[str, Any] = {
            "model": f"agent:{agent_id}" if agent_id else "openakita-auto",
            "messages": self._messages(message, system),
            "stream": True,
            "metadata": {"agent_profile_id": agent_id, **(metadata or {})},
        }
        if tools:
            payload["tools"] = tools
        async with (
            httpx.AsyncClient(timeout=self.node.timeout_seconds) as client,
            client.stream(
                "POST",
                f"{self.node.base_url}/v1/chat/completions",
                headers={
                    **self._headers(session_id=session_id, agent_id=agent_id),
                    "Accept": "text/event-stream",
                },
                json=payload,
            ) as response,
        ):
                response.raise_for_status()
                event_name = ""
                async for line in response.aiter_lines():
                    if not line:
                        event_name = ""
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                        continue
                    raw = line[5:].strip() if line.startswith("data:") else line.strip()
                    if raw == "[DONE]":
                        yield {"type": "done"}
                        return
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if event_name == "hermes.tool.progress":
                        yield {"type": "tool_progress", "event": data}
                        continue

                    choices = data.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield {"type": "text_delta", "content": str(content)}
                    if delta.get("tool_calls"):
                        yield {"type": "tool_call_delta", "tool_calls": delta["tool_calls"]}
                    finish_reason = choices[0].get("finish_reason")
                    if finish_reason:
                        yield {"type": "done", "finish_reason": finish_reason}
                        return
