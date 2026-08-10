from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException


HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load(HERE / "plugin_api.py", "hermes_extensions_dashboard_base_api")
compat = _load(PLUGIN_ROOT / "compatibility.py", "hermes_extensions_compatibility")

router = APIRouter()


def _caps():
    return compat.detect_capabilities()


def _unsupported() -> dict[str, Any]:
    payload = compat.project_unavailable_payload()
    payload["capabilities"] = _caps().to_dict()
    return payload


@router.get("/management/overview")
def management_overview() -> dict[str, Any]:
    caps = _caps()
    manager = base.ManagementCenter()
    if caps.project:
        data = manager.overview()
    else:
        agents = manager.agent_list(probe_runtime=True)
        errors = [
            {"scope": f"agent:{agent['name']}", "message": str(agent["status_error"])}
            for agent in agents if agent.get("status_error")
        ]
        errors.append({"scope": "projects", "message": compat.project_unavailable_payload()["message"]})
        data = {
            "counts": {
                "agents": len(agents),
                "running_agents": sum(
                    1 for agent in agents
                    if str(agent.get("gateway") or "").lower().startswith("running")
                ),
                "projects": 0,
                "archived_projects": 0,
            },
            "agents": agents,
            "projects": [],
            "active_profile": manager._active_profile(),
            "partial": bool(errors),
            "errors": errors,
        }
    tasks = base.TaskCenter().overview(include_completed=False)
    data["task_counts"] = tasks.get("counts", {})
    data["upcoming"] = base.TaskCenter().upcoming(hours=24 * 7, limit=25)
    data["capabilities"] = caps.to_dict()
    data["project_supported"] = caps.project
    return data


@router.get("/capabilities")
def capabilities() -> dict[str, Any]:
    caps = _caps()
    return {"capabilities": caps.to_dict(), "project_supported": caps.project}


@router.get("/projects")
def projects(profile: str | None = None, include_archived: bool = True) -> dict[str, Any]:
    if not _caps().project:
        return _unsupported()
    return base.projects(profile=profile, include_archived=include_archived)


@router.get("/projects/{project}")
def project_get(project: str, profile: str = "default") -> dict[str, Any]:
    if not _caps().project:
        return _unsupported()
    return base.project_get(project=project, profile=profile)


@router.post("/projects")
def project_create(body: base.ProjectBody) -> dict[str, Any]:
    if not _caps().project:
        raise HTTPException(status_code=409, detail=_unsupported())
    return base.project_create(body)


@router.patch("/projects/{project}")
def project_update(project: str, body: base.ProjectBody) -> dict[str, Any]:
    if not _caps().project:
        raise HTTPException(status_code=409, detail=_unsupported())
    return base.project_update(project, body)


@router.post("/projects/{project}/action")
def project_action(project: str, body: base.ActionBody) -> dict[str, Any]:
    if not _caps().project:
        raise HTTPException(status_code=409, detail=_unsupported())
    return base.project_action(project, body)


# Compatibility routes are registered first so they win for overlapping
# project/overview paths. All other Task/Agent routes come from the normal API.
router.include_router(base.router)
