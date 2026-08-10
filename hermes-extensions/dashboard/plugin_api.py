from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _load_class(relative: str, module_name: str, class_name: str):
    path = PLUGIN_ROOT / relative
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {class_name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, class_name)


TaskCenter = _load_class("task_center/service.py", "hermes_extensions_task_center_service", "TaskCenter")
ManagementCenter = _load_class("management/service.py", "hermes_extensions_management_service", "ManagementCenter")

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


class AgentBody(BaseModel):
    name: str | None = None
    description: str | None = None
    clone_mode: str | None = None
    clone_from: str | None = None
    no_skills: bool | None = None
    workspace: str | None = None
    model: str | None = None
    provider: str | None = None
    soul: str | None = None


class ProjectBody(BaseModel):
    name: str | None = None
    profile: str | None = None
    slug: str | None = None
    folders: list[str] | None = None
    primary: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    board: str | None = None
    use: bool | None = None
    agent: str | None = None
    add_folders: list[str] | None = None
    remove_folders: list[str] | None = None


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Task Center
# ---------------------------------------------------------------------------
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
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/tasks/{task_type}/{task_id}")
def update_task(task_type: str, task_id: str, body: TaskBody) -> dict[str, Any]:
    payload = body.model_dump(exclude_none=True)
    payload.update({"type": task_type, "id": task_id})
    try:
        return TaskCenter().update(payload)
    except ValueError as exc:
        raise _bad_request(exc) from exc
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
        raise _bad_request(exc) from exc
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
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Management Center
# ---------------------------------------------------------------------------
@router.get("/management/overview")
def management_overview() -> dict[str, Any]:
    try:
        data = ManagementCenter().overview()
        tasks = TaskCenter().overview(include_completed=False)
        data["task_counts"] = tasks.get("counts", {})
        data["upcoming"] = TaskCenter().upcoming(hours=24 * 7, limit=25)
        return data
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/agents")
def agents() -> dict[str, Any]:
    try:
        return {"items": ManagementCenter().agent_list()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/agents/{name}")
def agent_get(name: str) -> dict[str, Any]:
    try:
        data = ManagementCenter().agent_get(name)
        data["tasks"] = TaskCenter().overview(profile=name, include_completed=True)
        return data
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/agents")
def agent_create(body: AgentBody) -> dict[str, Any]:
    try:
        return ManagementCenter().agent_create(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/agents/{name}")
def agent_update(name: str, body: AgentBody) -> dict[str, Any]:
    try:
        return ManagementCenter().agent_update(name, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/agents/{name}/action")
def agent_action(name: str, body: ActionBody) -> dict[str, Any]:
    try:
        return ManagementCenter().agent_action(name, body.action, body.value)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/agents/{name}")
def agent_delete(name: str) -> dict[str, Any]:
    try:
        return ManagementCenter().agent_delete(name)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/projects")
def projects(profile: str | None = None, include_archived: bool = True) -> dict[str, Any]:
    try:
        return {"items": ManagementCenter().project_list(profile, include_archived=include_archived)}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/projects/{project}")
def project_get(project: str, profile: str = "default") -> dict[str, Any]:
    try:
        return ManagementCenter().project_get(project, profile)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/projects")
def project_create(body: ProjectBody) -> dict[str, Any]:
    try:
        return ManagementCenter().project_create(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/projects/{project}")
def project_update(project: str, body: ProjectBody) -> dict[str, Any]:
    payload = body.model_dump(exclude_none=True)
    profile = str(payload.pop("profile", "default"))
    try:
        return ManagementCenter().project_update(project, profile, payload)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/projects/{project}/action")
def project_action(project: str, body: ActionBody) -> dict[str, Any]:
    try:
        return ManagementCenter().project_action(project, body.profile or "default", body.action, body.value)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
