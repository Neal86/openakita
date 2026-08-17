"""OpenAI-compatible request/response conversion for the internal LLM gateway."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from openakita.llm.types import Message, TextBlock, Tool, ToolResultBlock, ToolUseBlock


def split_system(messages: list[dict[str, Any]]) -> tuple[str, list[Message]]:
    system_parts: list[str] = []
    converted: list[Message] = []
    for raw in messages:
        role = str(raw.get("role") or "user")
        content = raw.get("content", "")
        if role == "system":
            if isinstance(content, str):
                system_parts.append(content)
            elif isinstance(content, list):
                system_parts.extend(str(part.get("text") or "") for part in content if isinstance(part, dict))
            continue
        blocks: list[Any] = []
        if role == "tool":
            blocks.append(ToolResultBlock(tool_use_id=str(raw.get("tool_call_id") or "tool"), content=content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)))
            converted.append(Message(role="user", content=blocks))
            continue
        if isinstance(content, str):
            blocks.append(TextBlock(text=content))
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") in {"text", "input_text"}:
                    blocks.append(TextBlock(text=str(part.get("text") or "")))
        for call in raw.get("tool_calls") or []:
            fn = call.get("function") or {}
            arguments = fn.get("arguments") or "{}"
            try:
                parsed = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
            except Exception:
                parsed = {"raw": str(arguments)}
            blocks.append(ToolUseBlock(id=str(call.get("id") or uuid.uuid4().hex), name=str(fn.get("name") or "tool"), input=parsed))
        converted.append(Message(role=role, content=blocks or [TextBlock(text="")]))
    return "\n\n".join(part for part in system_parts if part), converted


def convert_tools(raw_tools: list[dict[str, Any]] | None) -> list[Tool] | None:
    if not raw_tools:
        return None
    result: list[Tool] = []
    for item in raw_tools:
        fn = item.get("function") if item.get("type") == "function" else item
        if not isinstance(fn, dict) or not fn.get("name"):
            continue
        result.append(Tool(name=str(fn["name"]), description=str(fn.get("description") or ""), input_schema=fn.get("parameters") or {"type": "object", "properties": {}}))
    return result or None


def completion_response(response: Any, *, requested_model: str) -> dict[str, Any]:
    tool_calls = []
    for block in getattr(response, "tool_calls", []) or []:
        tool_calls.append({
            "id": block.id,
            "type": "function",
            "function": {"name": block.name, "arguments": json.dumps(block.input, ensure_ascii=False)},
        })
    message: dict[str, Any] = {"role": "assistant", "content": getattr(response, "text", "") or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    usage = getattr(response, "usage", None)
    prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    stop_reason = str(getattr(getattr(response, "stop_reason", None), "value", "stop"))
    return {
        "id": getattr(response, "id", None) or f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": getattr(response, "model", None) or requested_model,
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if tool_calls else ("length" if "max" in stop_reason else "stop")}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens},
    }


def chunk(request_id: str, model: str, delta: dict[str, Any], finish_reason: str | None = None) -> str:
    payload = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
