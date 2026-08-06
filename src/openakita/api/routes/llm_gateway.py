"""Internal OpenAI-compatible LLM gateway used by Hermes containers.

No additional API key is required.  Deployment keeps /v1 on the private Docker
network; it must not be routed publicly.  The gateway calls LLMClient directly
and therefore cannot recurse into Agent -> Hermes routing.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from openakita.api.openai_compat import chunk, completion_response, convert_tools, split_system
from openakita.llm.client import LLMClient

router = APIRouter(prefix="/v1", tags=["LLM Gateway"])


class ChatCompletionRequest(BaseModel):
    model: str = "openakita-auto"
    messages: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] | None = None
    stream: bool = False
    temperature: float = 1.0
    max_tokens: int = 0
    user: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def _profile_id(model: str, payload: ChatCompletionRequest) -> str | None:
    if model.startswith("agent:"):
        return model.split(":", 1)[1].strip() or None
    value = payload.metadata.get("agent_profile_id")
    return str(value).strip() if value else None


def _profile_from_app(request: Request, profile_id: str) -> Any | None:
    candidates = [
        getattr(request.app.state, "profile_store", None),
        getattr(getattr(request.app.state, "orchestrator", None), "profile_store", None),
        getattr(getattr(request.app.state, "agent_pool", None), "profile_store", None),
    ]
    for store in candidates:
        getter = getattr(store, "get", None)
        if callable(getter):
            profile = getter(profile_id)
            if profile is not None:
                return profile
    # Robust fallback for serve-mode layouts.
    try:
        from openakita.config import settings
        roots = [Path(settings.project_root) / "data" / "agents" / "profiles", Path(settings.project_root) / "data" / "profiles"]
        from openakita.agents.profile import AgentProfile
        for root in roots:
            path = root / f"{profile_id}.json"
            if path.exists():
                return AgentProfile.from_dict(json.loads(path.read_text("utf-8")))
    except Exception:
        pass
    return None


def _clients_for(request: Request, payload: ChatCompletionRequest) -> tuple[list[LLMClient], str]:
    full = LLMClient()
    profile_id = _profile_id(payload.model, payload)
    profile = _profile_from_app(request, profile_id) if profile_id else None
    preferred = getattr(profile, "preferred_endpoint", None) if profile else None
    policy = getattr(profile, "endpoint_policy", "prefer") if profile else "prefer"

    # endpoint:<name> remains available for diagnostics; normal Hermes calls use agent:<id>.
    if payload.model.startswith("endpoint:"):
        preferred = payload.model.split(":", 1)[1]
        policy = "require"

    if not preferred:
        return [full], profile_id or "openakita-auto"
    matched = [endpoint for endpoint in full.endpoints if endpoint.name == preferred or endpoint.model == preferred]
    if not matched:
        if policy == "require":
            raise HTTPException(status_code=400, detail=f"Agent requires unavailable endpoint: {preferred}")
        return [full], profile_id or payload.model
    selected = LLMClient(endpoints=matched)
    return ([selected] if policy == "require" else [selected, full]), profile_id or payload.model


def _call_kwargs(payload: ChatCompletionRequest) -> dict[str, Any]:
    system, messages = split_system(payload.messages)
    return {
        "messages": messages,
        "system": system,
        "tools": convert_tools(payload.tools),
        "max_tokens": max(0, payload.max_tokens),
        "temperature": payload.temperature,
        "conversation_id": payload.user or payload.metadata.get("conversation_id"),
    }


@router.get("/health")
def gateway_health() -> dict[str, Any]:
    client = LLMClient()
    return {"status": "ok", "service": "openakita-llm-gateway", "models": len(client.endpoints)}


@router.get("/models")
def list_gateway_models() -> dict[str, Any]:
    now = int(time.time())
    client = LLMClient()
    data = [{"id": "openakita-auto", "object": "model", "created": now, "owned_by": "openakita"}]
    seen = {"openakita-auto"}
    for endpoint in client.endpoints:
        for model_id in (f"endpoint:{endpoint.name}", endpoint.model):
            if model_id and model_id not in seen:
                data.append({"id": model_id, "object": "model", "created": now, "owned_by": endpoint.provider or "openakita"})
                seen.add(model_id)
    return {"object": "list", "data": data}


@router.post("/chat/completions")
async def chat_completions(payload: ChatCompletionRequest, request: Request):
    if not payload.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")
    clients, display_model = _clients_for(request, payload)
    kwargs = _call_kwargs(payload)

    if not payload.stream:
        errors: list[str] = []
        for client in clients:
            try:
                response = await client.chat(**kwargs)
                return completion_response(response, requested_model=display_model)
            except Exception as exc:
                errors.append(str(exc))
        raise HTTPException(status_code=502, detail="All configured model endpoints failed: " + "; ".join(errors))

    async def events() -> AsyncIterator[str]:
        request_id = f"chatcmpl-{uuid.uuid4().hex}"
        yield chunk(request_id, display_model, {"role": "assistant"})
        errors: list[str] = []
        for client in clients:
            yielded_content = False
            try:
                async for event in client.chat_stream(**kwargs):
                    event_type = str(event.get("type") or "") if isinstance(event, dict) else ""
                    if event_type in {"text_delta", "content_delta", "text"}:
                        text = str(event.get("content") or event.get("text") or "")
                        if text:
                            yielded_content = True
                            yield chunk(request_id, display_model, {"content": text})
                    elif event_type in {"tool_use", "tool_call"}:
                        yielded_content = True
                        call_id = str(event.get("id") or uuid.uuid4().hex)
                        name = str(event.get("name") or "tool")
                        arguments = event.get("input") or event.get("arguments") or {}
                        if not isinstance(arguments, str):
                            arguments = json.dumps(arguments, ensure_ascii=False)
                        yield chunk(request_id, display_model, {"tool_calls": [{"index": 0, "id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}]})
                yield chunk(request_id, display_model, {}, "stop")
                yield "data: [DONE]\n\n"
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                errors.append(str(exc))
                if yielded_content:
                    yield chunk(request_id, display_model, {}, "stop")
                    yield "data: [DONE]\n\n"
                    return
        error = {"error": {"message": "All configured model endpoints failed: " + "; ".join(errors), "type": "upstream_error"}}
        yield "data: " + json.dumps(error, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
