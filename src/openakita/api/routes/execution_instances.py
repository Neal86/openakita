"""Agent execution-mode and Hermes instance management API."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from openakita.hermes.container_manager import ContainerManagerError, HermesContainerManager
from openakita.hermes.execution import (
    AgentExecutionConfig,
    AgentExecutionStore,
    ExecutionMode,
    HermesInstanceMode,
    HermesInstanceStore,
    SubAgentMemoryMode,
)
from openakita.hermes.lifecycle import HermesLifecycleService
from openakita.hermes.router import HermesRouter

router = APIRouter(prefix="/execution", tags=["执行模式"])


class ExecutionPayload(BaseModel):
    execution_mode: ExecutionMode = ExecutionMode.NATIVE
    hermes_instance_mode: HermesInstanceMode = HermesInstanceMode.SHARED
    hermes_instance_id: str | None = None
    hermes_allow_sub_agents: bool = False
    hermes_sub_agent_memory_mode: SubAgentMemoryMode = SubAgentMemoryMode.EPHEMERAL


@router.get("/agents/{profile_id}")
def get_agent_execution(profile_id: str) -> dict:
    return {"execution": AgentExecutionStore().get(profile_id).to_dict()}


@router.put("/agents/{profile_id}")
async def set_agent_execution(profile_id: str, payload: ExecutionPayload) -> dict:
    config = AgentExecutionConfig(profile_id=profile_id, **payload.model_dump())
    service = HermesLifecycleService()
    config, instance = await service.apply(config)
    AgentExecutionStore().upsert(config)
    return {
        "execution": config.to_dict(),
        "instance": instance.to_dict() if instance else None,
    }


@router.delete("/agents/{profile_id}")
def reset_agent_execution(profile_id: str) -> dict:
    AgentExecutionStore().delete(profile_id)
    return {"deleted": True, "execution": AgentExecutionConfig(profile_id).to_dict()}


@router.get("/instances")
async def list_instances() -> dict:
    service = HermesLifecycleService()
    service.ensure_shared()
    rows = []
    for instance in service.instances.list():
        data = instance.to_dict()
        if HermesContainerManager.available():
            try:
                data["container"] = await service.containers.inspect(instance)
            except Exception as exc:
                data["container"] = {"exists": False, "running": False, "error": str(exc)}
        else:
            data["container"] = {"available": False, "error": "Docker socket unavailable"}
        bindings = [x.to_dict() for x in AgentExecutionStore().list() if x.hermes_instance_id == instance.id or (instance.id == "shared" and x.execution_mode == ExecutionMode.HERMES and x.hermes_instance_mode == HermesInstanceMode.SHARED)]
        data["agents"] = bindings
        data["agent_count"] = len(bindings)
        rows.append(data)
    return {"instances": rows, "docker_available": HermesContainerManager.available()}


@router.get("/instances/{instance_id}")
def get_instance(instance_id: str) -> dict:
    instance = HermesInstanceStore().get(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="执行模式实例不存在")
    return {"instance": instance.to_dict()}


@router.post("/instances/{instance_id}/start")
async def start_instance(instance_id: str) -> dict:
    instance = HermesInstanceStore().get(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="执行模式实例不存在")
    try:
        updated = await HermesContainerManager().create_or_start(instance)
    except ContainerManagerError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    HermesInstanceStore().upsert(updated)
    return {"instance": updated.to_dict()}


@router.post("/instances/{instance_id}/stop")
async def stop_instance(instance_id: str) -> dict:
    instance = HermesInstanceStore().get(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="执行模式实例不存在")
    try:
        updated = await HermesLifecycleService().stop(instance)
    except ContainerManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"instance": updated.to_dict()}


@router.post("/instances/{instance_id}/restart")
async def restart_instance(instance_id: str) -> dict:
    instance = HermesInstanceStore().get(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="执行模式实例不存在")
    try:
        updated = await HermesLifecycleService().restart(instance)
    except ContainerManagerError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"instance": updated.to_dict()}


@router.post("/instances/{instance_id}/test")
async def test_instance(instance_id: str) -> dict:
    try:
        return await HermesRouter().test_node(instance_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="执行模式实例不存在") from None


@router.get("/instances/{instance_id}/logs")
async def instance_logs(instance_id: str, tail: int = Query(200, ge=1, le=1000)) -> dict:
    instance = HermesInstanceStore().get(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="执行模式实例不存在")
    if not HermesContainerManager.available():
        raise HTTPException(status_code=503, detail="Docker socket unavailable")
    return {"logs": await HermesContainerManager().logs(instance, tail=tail)}


@router.delete("/instances/{instance_id}")
async def delete_instance(instance_id: str, delete_data: bool = False) -> dict:
    instance = HermesInstanceStore().get(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="执行模式实例不存在")
    try:
        await HermesLifecycleService().remove(instance, delete_data=delete_data)
    except ContainerManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": True, "delete_data": delete_data}
