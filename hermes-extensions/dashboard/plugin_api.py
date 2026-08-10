from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

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
    type: Literal["cron", "kanban"] | None = None
    name: str | None = Field(default=None, max_length=256)
    prompt: str | None = Field(default=None, max_length=20000)
    schedule: str | None = Field(default=None, max_length=256)
    profile: str | None = Field(default=None, max_length=64)
    priority: int | None = Field(default=None, ge=0, le=100)
    deliver: str | None = Field(default=None, max_length=128)


class TaskActionBody(BaseModel):
    action: Literal["pause", "resume", "run", "remove", "assign", "archive"]
    value: str | None = None
    profile: str | None = Field(default=None, max_length=64)


class AgentBody(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    clone_mode: Literal["blank", "clone", "clone_all"] | None = None
    clone_from: str | None = Field(default=None, max_length=64)
    no_skills: bool | None = None
    workspace: str | None = Field(default=None, max_length=4096)
    model: str | None = Field(default=None, max_length=512)
    provider: str | None = Field(default=None, max_length=128)
    soul: str | None = Field(default=None, max_length=200000)


class AgentActionBody(BaseModel):
    action: Literal[
        "use",
        "gateway_start",
        "gateway_stop",
        "gateway_restart",
        "gateway_status",
        "set_workspace",
        "export",
    ]
    value: str | None = Field(default=None, max_length=4096)


class ProjectBody(BaseModel):
    name: str | None = Field(default=None, max_length=256)
    profile: str | None = Field(default=None, max_length=64)
    slug: str | None = Field(default=None, max_length=128)
    folders: list[str] | None = None
    primary: str | None = Field(default=None, max_length=4096)
    description: str | None = Field(default=None, max_length=2000)
    icon: str | None = Field(default=None, max_length=128)
    color: str | None = Field(default=None, max_length=64)
    board: str | None = Field(default=None, max_length=128)
    use: bool | None = None
    agent: str | None = Field(default=None, max_length=64)
    add_folders: list[str] | None = None
    remove_folders: list[str] | None = None


class ProjectActionBody(BaseModel):
    action: Literal["use", "archive", "restore", "add_folder", "remove_folder", "set_primary", "bind_board", "assign_agent"]
    value: str | None = Field(default=None, max_length=4096)
    profile: str | None = Field(default=None, max_length=64)


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _server_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=500, detail=str(exc))


def _management_overview() -> dict[str, Any]:
    data = ManagementCenter().overview()
    task_center = TaskCenter()
    tasks = task_center.overview(include_completed=False)
    data["task_counts"] = tasks.get("counts", {})
    data["upcoming"] = task_center.upcoming(hours=24 * 7, limit=25)
    if tasks.get("kanban_error"):
        data.setdefault("errors", []).append({"scope": "tasks:kanban", "message": str(tasks["kanban_error"])})
        data["partial"] = True
    return data


@router.get("/overview")
def overview(profile: str | None = None, include_completed: bool = False) -> dict[str, Any]:
    try:
        return TaskCenter().overview(profile=profile, include_completed=include_completed)
    except Exception as exc:
        raise _server_error(exc) from exc


@router.get("/upcoming")
def upcoming(
    hours: int = Query(168, ge=1, le=2160),
    profile: str | None = None,
    limit: int = Query(300, ge=1, le=1000),
) -> dict[str, Any]:
    try:
        return {"items": TaskCenter().upcoming(hours=hours, profile=profile, limit=limit)}
    except Exception as exc:
        raise _server_error(exc) from exc


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
        raise _server_error(exc) from exc


@router.patch("/tasks/{task_type}/{task_id}")
def update_task(task_type: Literal["cron", "kanban"], task_id: str, body: TaskBody) -> dict[str, Any]:
    payload = body.model_dump(exclude_none=True)
    payload.update({"type": task_type, "id": task_id})
    try:
        return TaskCenter().update(payload)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.post("/tasks/{task_type}/{task_id}/action")
def task_action(task_type: Literal["cron", "kanban"], task_id: str, body: TaskActionBody) -> dict[str, Any]:
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
        raise _server_error(exc) from exc


@router.get("/tasks/{task_type}/{task_id}/history")
def history(
    task_type: Literal["cron", "kanban"],
    task_id: str,
    profile: str | None = None,
    limit: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    try:
        return {"items": TaskCenter().history(task_type, task_id, limit=limit, profile=profile)}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.get("/management/overview")
def management_overview() -> dict[str, Any]:
    try:
        return _management_overview()
    except Exception as exc:
        raise _server_error(exc) from exc


@router.get("/agents")
def agents() -> dict[str, Any]:
    try:
        return {"items": ManagementCenter().agent_list()}
    except Exception as exc:
        raise _server_error(exc) from exc


@router.get("/agents/{name}")
def agent_get(name: str) -> dict[str, Any]:
    try:
        data = ManagementCenter().agent_get(name)
        data["tasks"] = TaskCenter().overview(profile=name, include_completed=True)
        return data
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.post("/agents")
def agent_create(body: AgentBody) -> dict[str, Any]:
    try:
        return ManagementCenter().agent_create(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.patch("/agents/{name}")
def agent_update(name: str, body: AgentBody) -> dict[str, Any]:
    try:
        return ManagementCenter().agent_update(name, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.post("/agents/{name}/action")
def agent_action(name: str, body: AgentActionBody) -> dict[str, Any]:
    try:
        return ManagementCenter().agent_action(name, body.action, body.value)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.delete("/agents/{name}")
def agent_delete(name: str) -> dict[str, Any]:
    try:
        return ManagementCenter().agent_delete(name)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.get("/projects")
def projects(profile: str | None = None, include_archived: bool = True) -> dict[str, Any]:
    try:
        return {"items": ManagementCenter().project_list(profile, include_archived=include_archived)}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.get("/projects/{project}")
def project_get(project: str, profile: str = "default") -> dict[str, Any]:
    try:
        return ManagementCenter().project_get(project, profile)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.post("/projects")
def project_create(body: ProjectBody) -> dict[str, Any]:
    try:
        return ManagementCenter().project_create(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.patch("/projects/{project}")
def project_update(project: str, body: ProjectBody) -> dict[str, Any]:
    payload = body.model_dump(exclude_none=True)
    profile = str(payload.pop("profile", "default"))
    try:
        return ManagementCenter().project_update(project, profile, payload)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.post("/projects/{project}/action")
def project_action(project: str, body: ProjectActionBody) -> dict[str, Any]:
    try:
        return ManagementCenter().project_action(project, body.profile or "default", body.action, body.value)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc
