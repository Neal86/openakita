"""HTTP/SSE client for Hermes Agent runtimes."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from .models import HermesNode


@dataclass
class HermesResponse:
    content: str
    node_id: str
    usage: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class HermesClient:
    def __init__(self, node: HermesNode) -> None:
        self.node = node

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.node.api_key_env:
            key = os.environ.get(self.node.api_key_env, "").strip()
            if key:
                headers["Authorization"] = f"Bearer {key}"
        return headers

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
        payload = {
            "agent_id": agent_id,
            "session_id": session_id,
            "message": message,
            "system": system,
            "tools": tools or [],
            "metadata": metadata or {},
        }
        async with httpx.AsyncClient(timeout=self.node.timeout_seconds) as client:
            response = await client.post(
                f"{self.node.base_url}/v1/agent/run", headers=self._headers(), json=payload
            )
            response.raise_for_status()
            data = response.json()
        content = data.get("content") or data.get("output") or data.get("message") or ""
        return HermesResponse(
            content=str(content),
            node_id=self.node.id,
            usage=data.get("usage") or {},
            metadata=data.get("metadata") or {},
        )

    async def run_stream(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        payload = dict(kwargs)
        async with httpx.AsyncClient(timeout=self.node.timeout_seconds) as client:
            async with client.stream(
                "POST",
                f"{self.node.base_url}/v1/agent/run/stream",
                headers={**self._headers(), "Accept": "text/event-stream"},
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or line.startswith(":"):
                        continue
                    raw = line[5:].strip() if line.startswith("data:") else line.strip()
                    if raw == "[DONE]":
                        yield {"type": "done"}
                        return
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        event = {"type": "text_delta", "content": raw}
                    yield event
