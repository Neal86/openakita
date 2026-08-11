from __future__ import annotations

from typing import Any


def build_management_overview(
    *,
    caps: Any,
    manager: Any,
    task_center: Any,
    project_unavailable_message: str,
) -> dict[str, Any]:
    """Build the canonical management/task summary from already-resolved services.

    Callers resolve capabilities and service instances once, preventing duplicate
    Hermes capability probes or duplicate module caches in Dashboard/tool paths.
    """
    if caps.project:
        data = manager.overview()
    else:
        agents = manager.agent_list(probe_runtime=True)
        errors = [
            {"scope": f"agent:{agent['name']}", "message": str(agent["status_error"])}
            for agent in agents
            if agent.get("status_error")
        ]
        errors.append({"scope": "projects", "message": project_unavailable_message})
        data = {
            "counts": {
                "agents": len(agents),
                "running_agents": sum(
                    1
                    for agent in agents
                    if str(agent.get("gateway") or "").lower().startswith("running")
                ),
                "projects": 0,
                "archived_projects": 0,
            },
            "agents": agents,
            "projects": [],
            "active_profile": manager._active_profile(),
            "partial": True,
            "errors": errors,
        }

    tasks = task_center.overview(include_completed=False)
    data["task_counts"] = tasks.get("counts", {})
    data["upcoming"] = task_center.upcoming(hours=24 * 7, limit=25)
    if tasks.get("kanban_error"):
        data.setdefault("errors", []).append(
            {"scope": "tasks:kanban", "message": str(tasks["kanban_error"])}
        )
        data["partial"] = True
    data["capabilities"] = caps.to_dict()
    data["project_supported"] = caps.project
    return data
