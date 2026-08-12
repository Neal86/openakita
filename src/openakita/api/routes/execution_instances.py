"""Agent execution-mode and Hermes instance management API."""
from __future__ import annotations

import os
import sys
from dataclasses import replace
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from openakita.hermes.bindings import AgentHermesBindingStore
from openakita.hermes.container_manager import ContainerManagerError, HermesContainerManager
from openakita.hermes.execution import (
    AgentExecutionConfig,
    AgentExecutionStore,
    ExecutionMode,
    HermesInstanceMode,
    HermesInstanceStore,
    InstanceLifecycle,
    SubAgentMemoryMode,
)
from openakita.hermes.lifecycle import HermesLifecycleService
from openakita.hermes.native_runtime import NativeHermesRuntime
from openakita.hermes.router import HermesRouter

router = APIRouter(prefix="/api/execution", tags=["执行模式"])


class ExecutionPayload(BaseModel):
    execution_mode: ExecutionMode = ExecutionMode.NATIVE
    hermes_instance_mode: HermesInstanceMode = HermesInstanceMode.SHARED
    hermes_instance_id: str | None = None
    hermes_allow_sub_agents: bool = False
    hermes_sub_agent_memory_mode: SubAgentMemoryMode = SubAgentMemoryMode.EPHEMERAL


def _normalized_instance(instance):
    return HermesLifecycleService().normalize_instance(instance)


def _native_info(instance) -> dict:
    instance = _normalized_instance(instance)
    is_native = HermesLifecycleService.is_native(instance)
    if not is_native:
        return {"transport": "docker", "native": False}
    available = NativeHermesRuntime.available()
    running = bool(
        instance.enabled
        and available
        and instance.lifecycle_status == InstanceLifecycle.RUNNING
    )
    return {
        "transport": "native_windows" if sys.platform == "win32" else "native",
        "native": True,
        "available": available,
        "running": running,
        "pid": os.getpid() if available else None,
        "version": NativeHermesRuntime.version(),
        "process_model": "embedded_backend",
    }


def _native_logs(instance, tail: int) -> str:
    instance = _normalized_instance(instance)
    info = _native_info(instance)
    rows = [
        f"[{datetime.now(UTC).isoformat()}] Hermes embedded runtime",
        f"instance={instance.id}",
        f"transport={info.get('transport')}",
        f"version={info.get('version')}",
        f"backend_pid={info.get('pid')}",
        f"enabled={instance.enabled}",
        f"lifecycle={instance.lifecycle_status.value}",
        f"health={instance.health_status}",
        f"base_url={instance.base_url}",
        f"last_success_at={instance.last_success_at or '-'}",
        f"last_error={instance.last_error or '-'}",
        "Native Hermes is embedded in the OpenAkita backend; the PID above belongs to the backend process.",
    ]
    return "\n".join(rows[-max(1, tail):])


def _bound_profiles(instance_id: str) -> list[str]:
    profiles: list[str] = []
    for config in AgentExecutionStore().list():
        bound = config.hermes_instance_id == instance_id
        shared = (
            instance_id == HermesLifecycleService.SHARED_ID
            and config.execution_mode == ExecutionMode.HERMES
            and config.hermes_instance_mode == HermesInstanceMode.SHARED
        )
        if bound or shared:
            profiles.append(config.profile_id)
    return sorted(set(profiles))


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
    AgentHermesBindingStore().delete(profile_id)
    return {
        "deleted": True,
        "execution": AgentExecutionConfig(profile_id).to_dict(),
    }


@router.get("/instances")
async def list_instances() -> dict:
    service = HermesLifecycleService()
    service.ensure_shared()
    executions = AgentExecutionStore().list()
    rows = []
    for stored in service.instances.list():
        instance = _normalized_instance(stored)
        runtime = _native_info(instance)
        data = instance.to_dict()
        data["runtime"] = runtime
        if runtime.get("native"):
            data["container"] = {
                "available": False,
                "exists": False,
                "running": runtime.get("running", False),
                "native": True,
            }
            if runtime.get("available") and instance.enabled:
                data["health_status"] = instance.health_status or "unknown"
        elif HermesContainerManager.available():
            try:
                data["container"] = await service.containers.inspect(instance)
            except Exception as exc:
                data["container"] = {
                    "exists": False,
                    "running": False,
                    "error": str(exc),
                }
        else:
            data["container"] = {
                "available": False,
                "error": "Docker socket unavailable",
            }
        bindings = [
            item.to_dict()
            for item in executions
            if item.hermes_instance_id == instance.id
            or (
                instance.id == "shared"
                and item.execution_mode == ExecutionMode.HERMES
                and item.hermes_instance_mode == HermesInstanceMode.SHARED
            )
        ]
        data["agents"] = bindings
        data["agent_count"] = len(bindings)
        rows.append(data)
    return {
        "instances": rows,
        "docker_available": HermesContainerManager.available(),
        "native_available": NativeHermesRuntime.available(),
        "native_default": HermesLifecycleService.native_default(),
        "platform": sys.platform,
    }


@router.get("/instances/{instance_id}")
def get_instance(instance_id: str) -> dict:
    instance = HermesInstanceStore().get(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="执行模式实例不存在")
    instance = _normalized_instance(instance)
    data = instance.to_dict()
    data["runtime"] = _native_info(instance)
    return {"instance": data}


@router.post("/instances/{instance_id}/start")
async def start_instance(instance_id: str) -> dict:
    instance = HermesInstanceStore().get(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="执行模式实例不存在")
    instance = _normalized_instance(instance)
    try:
        updated = await HermesLifecycleService().start(instance)
    except ContainerManagerError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"instance": updated.to_dict(), "runtime": _native_info(updated)}


@router.post("/instances/{instance_id}/stop")
async def stop_instance(instance_id: str) -> dict:
    instance = HermesInstanceStore().get(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="执行模式实例不存在")
    instance = _normalized_instance(instance)
    try:
        updated = await HermesLifecycleService().stop(instance)
    except ContainerManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"instance": updated.to_dict(), "runtime": _native_info(updated)}


@router.post("/instances/{instance_id}/restart")
async def restart_instance(instance_id: str) -> dict:
    instance = HermesInstanceStore().get(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="执行模式实例不存在")
    instance = _normalized_instance(instance)
    try:
        updated = await HermesLifecycleService().restart(instance)
    except ContainerManagerError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"instance": updated.to_dict(), "runtime": _native_info(updated)}


@router.post("/instances/{instance_id}/test")
async def test_instance(instance_id: str) -> dict:
    instance = HermesInstanceStore().get(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="执行模式实例不存在")
    instance = _normalized_instance(instance)
    if not instance.enabled or instance.lifecycle_status != InstanceLifecycle.RUNNING:
        raise HTTPException(status_code=409, detail="Hermes 实例尚未启动")
    if HermesLifecycleService.is_native(instance):
        if not NativeHermesRuntime.available():
            raise HTTPException(
                status_code=503,
                detail="Embedded Hermes runtime unavailable",
            )
        try:
            result = await NativeHermesRuntime.run(
                message="Reply exactly OPENAKITA_HERMES_OK and nothing else.",
                agent_id=instance.agent_profile_id or "default",
                session_id=f"health-{instance.id}",
                system="This is an OpenAkita runtime health check.",
                tools=[],
                metadata={"health_check": True},
            )
        except Exception as exc:
            failed = replace(
                instance,
                health_status="unhealthy",
                last_error=str(exc),
            )
            HermesInstanceStore().upsert(failed)
            raise HTTPException(
                status_code=503,
                detail=f"Hermes Runtime 测试失败: {exc}",
            ) from exc
        content = str(result.get("content") or "").strip()
        if "OPENAKITA_HERMES_OK" not in content:
            failed = replace(
                instance,
                health_status="degraded",
                last_error=f"unexpected health response: {content[:200]}",
            )
            HermesInstanceStore().upsert(failed)
            raise HTTPException(
                status_code=502,
                detail="Hermes Runtime 返回了异常的健康检查内容",
            )
        updated = replace(
            instance,
            health_status="healthy",
            last_success_at=datetime.now(UTC).isoformat(),
            last_error=None,
        )
        HermesInstanceStore().upsert(updated)
        return {
            "ok": True,
            "instance_id": instance.id,
            "runtime": _native_info(updated),
            "message": "Hermes Runtime 端到端测试通过",
        }
    try:
        return await HermesRouter().test_node(instance_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail="执行模式实例不存在",
        ) from None


@router.get("/instances/{instance_id}/logs")
async def instance_logs(
    instance_id: str,
    tail: int = Query(200, ge=1, le=1000),
) -> dict:
    instance = HermesInstanceStore().get(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="执行模式实例不存在")
    instance = _normalized_instance(instance)
    if HermesLifecycleService.is_native(instance):
        return {"logs": _native_logs(instance, tail)}
    if not HermesContainerManager.available():
        raise HTTPException(status_code=503, detail="Docker socket unavailable")
    return {"logs": await HermesContainerManager().logs(instance, tail=tail)}


@router.delete("/instances/{instance_id}")
async def delete_instance(instance_id: str, delete_data: bool = False) -> dict:
    instance = HermesInstanceStore().get(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="执行模式实例不存在")
    bound_profiles = _bound_profiles(instance.id)
    if bound_profiles:
        raise HTTPException(
            status_code=409,
            detail=(
                "该 Hermes 实例仍被 Agent 使用，请先切换这些 Agent 的执行模式: "
                + ", ".join(bound_profiles)
            ),
        )
    instance = _normalized_instance(instance)
    try:
        await HermesLifecycleService().remove(instance, delete_data=delete_data)
    except ContainerManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": True, "delete_data": delete_data}
