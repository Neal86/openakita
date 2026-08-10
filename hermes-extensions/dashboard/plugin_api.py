from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = PLUGIN_ROOT / "task_center" / "service.py"
_spec = importlib.util.spec_from_file_location("hermes_extensions_task_center_service", SERVICE_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError("Unable to load Hermes task center service")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
TaskCenter = _module.TaskCenter

router = APIRouter()


class TaskBody(BaseModel):
    type: str | None = None
    name: str | None = None
    prompt: str | None = None
    schedule: str | None = None
    profile: str | None = None
    priority: int | None = None
    deliver: str | None = None


class ActionBody(BaseModel):
    action: str
    value: str | None = None
    profile: str | None = None


@router.get("/overview")
def overview(profile: str | None = None, include_completed: bool = False) -> dict[str, Any]:
    try:
        return TaskCenter().overview(profile=profile, include_completed=include_completed)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/upcoming")
def upcoming(
    hours: int = Query(168, ge=1, le=2160),
    profile: str | None = None,
    limit: int = Query(300, ge=1, le=1000),
) -> dict[str, Any]:
    try:
        return {"items": TaskCenter().upcoming(hours=hours, profile=profile, limit=limit)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/tasks")
def create_task(body: TaskBody) -> dict[str, Any]:
    payload = body.model_dump(exclude_none=True)
    if not payload.get("type"):
        raise HTTPException(status_code=400, detail="type is required")
    try:
        return TaskCenter().create(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/tasks/{task_type}/{task_id}")
def update_task(task_type: str, task_id: str, body: TaskBody) -> dict[str, Any]:
    payload = body.model_dump(exclude_none=True)
    payload.update({"type": task_type, "id": task_id})
    try:
        return TaskCenter().update(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/tasks/{task_type}/{task_id}/action")
def task_action(task_type: str, task_id: str, body: ActionBody) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": task_type, "id": task_id, "action": body.action}
    if body.value is not None:
        payload["value"] = body.value
    if body.profile is not None:
        payload["profile"] = body.profile
    try:
        return TaskCenter().action(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/tasks/{task_type}/{task_id}/history")
def history(
    task_type: str,
    task_id: str,
    profile: str | None = None,
    limit: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    try:
        return {"items": TaskCenter().history(task_type, task_id, limit=limit, profile=profile)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
