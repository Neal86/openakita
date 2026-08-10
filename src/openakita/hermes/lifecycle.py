"""Execution-mode reconciliation between Agent config, instances and router nodes."""
from __future__ import annotations

import os
import sys
from dataclasses import replace

from .bindings import AgentHermesBinding, AgentHermesBindingStore
from .container_manager import ContainerManagerError, HermesContainerManager
from .execution import (
    AgentExecutionConfig,
    ExecutionMode,
    HermesInstance,
    HermesInstanceMode,
    HermesInstanceStore,
    InstanceLifecycle,
)
from .isolation import HermesIsolationManager
from .models import HermesNode, HermesRoutingPolicy, HermesRuntimeProvider
from .native_runtime import NativeHermesRuntime
from .store import get_hermes_store


class HermesLifecycleService:
    SHARED_ID = "shared"
    RUNTIME_IMAGE = "openakita-hermes-runtime:latest"

    def __init__(self) -> None:
        self.instances = HermesInstanceStore()
        self.containers = HermesContainerManager()
        self.isolation = HermesIsolationManager()

    @staticmethod
    def native_default() -> bool:
        """Desktop Windows uses embedded Hermes unless explicitly forced to Docker."""
        requested = os.environ.get("OPENAKITA_HERMES_RUNTIME", "").strip().lower()
        if requested in {"docker", "container", "remote"}:
            return False
        if requested in {"native", "embedded", "desktop"}:
            return True
        return sys.platform == "win32"

    @staticmethod
    def _native_url(instance_id: str) -> str:
        return f"native://{instance_id}"

    def ensure_shared(self) -> HermesInstance:
        instance = self.instances.get(self.SHARED_ID)
        use_native = self.native_default()
        if instance is None:
            instance = HermesInstance(
                id=self.SHARED_ID,
                name="Hermes 共享实例",
                mode=HermesInstanceMode.SHARED,
                image=self.RUNTIME_IMAGE,
                container_name="openakita-hermes-shared",
                volume_name="openakita_hermes_shared_data",
                base_url=self._native_url(self.SHARED_ID) if use_native else "http://openakita-hermes-shared:8642",
                lifecycle_status=(
                    InstanceLifecycle.RUNNING
                    if (not use_native or NativeHermesRuntime.available())
                    else InstanceLifecycle.ERROR
                ),
                last_error=(
                    None
                    if (not use_native or NativeHermesRuntime.available())
                    else "Embedded Hermes runtime unavailable"
                ),
                max_concurrency=16,
            )
            self.instances.upsert(instance)
        else:
            wanted_url = self._native_url(self.SHARED_ID) if use_native else "http://openakita-hermes-shared:8642"
            wanted_status = (
                InstanceLifecycle.RUNNING
                if (not use_native or NativeHermesRuntime.available())
                else InstanceLifecycle.ERROR
            )
            wanted_error = None if wanted_status == InstanceLifecycle.RUNNING else "Embedded Hermes runtime unavailable"
            if (
                instance.image != self.RUNTIME_IMAGE
                or instance.base_url != wanted_url
                or instance.lifecycle_status != wanted_status
                or instance.last_error != wanted_error
            ):
                instance = replace(
                    instance,
                    image=self.RUNTIME_IMAGE,
                    base_url=wanted_url,
                    lifecycle_status=wanted_status,
                    last_error=wanted_error,
                )
                self.instances.upsert(instance)
        self._register_node(instance)
        return instance

    def _register_node(self, instance: HermesInstance) -> None:
        node = get_hermes_store().get(instance.id)
        payload = {
            "id": instance.id,
            "name": instance.name,
            "base_url": instance.base_url,
            "enabled": instance.enabled,
            "priority": 10 if instance.mode == HermesInstanceMode.DEDICATED else 100,
            "weight": 1,
            "capabilities": ["text", "tools", "skills", "memory", "sub_agents", "mcp"],
            "tags": [instance.mode.value, "native" if instance.base_url.startswith("native://") else "container"],
            "max_concurrency": instance.max_concurrency,
            "timeout_seconds": 300,
        }
        if node is not None:
            payload.update({
                "health_status": node.health_status,
                "consecutive_failures": node.consecutive_failures,
                "last_success_at": node.last_success_at,
                "last_error": node.last_error,
                "current_inflight": node.current_inflight,
            })
        get_hermes_store().upsert(HermesNode(**payload))

    async def apply(self, config: AgentExecutionConfig, *, profile_metadata: dict | None = None) -> tuple[AgentExecutionConfig, HermesInstance | None]:
        if config.execution_mode == ExecutionMode.NATIVE:
            AgentHermesBindingStore().upsert(AgentHermesBinding(
                profile_id=config.profile_id,
                runtime_provider=HermesRuntimeProvider.LOCAL,
            ))
            return config, None

        self.isolation.ensure(config.profile_id, metadata=profile_metadata or config.to_dict())
        use_native = self.native_default()
        if config.hermes_instance_mode == HermesInstanceMode.SHARED:
            instance = self.ensure_shared()
            config.hermes_instance_id = instance.id
        else:
            instance_id = config.hermes_instance_id or f"dedicated-{config.profile_id}"
            instance = self.instances.get(instance_id) or HermesInstance(
                id=instance_id,
                name=f"{config.profile_id} 专属 Hermes",
                mode=HermesInstanceMode.DEDICATED,
                image=self.RUNTIME_IMAGE,
                agent_profile_id=config.profile_id,
                max_concurrency=4,
            )
            if instance.image != self.RUNTIME_IMAGE:
                instance = replace(instance, image=self.RUNTIME_IMAGE)

            if use_native:
                available = NativeHermesRuntime.available()
                instance = replace(
                    instance,
                    base_url=self._native_url(instance.id),
                    lifecycle_status=InstanceLifecycle.RUNNING if available else InstanceLifecycle.ERROR,
                    last_error=None if available else "Embedded Hermes runtime unavailable",
                )
            elif HermesContainerManager.available():
                try:
                    instance = await self.containers.create_or_start(instance)
                except Exception as exc:
                    instance = replace(instance, lifecycle_status=InstanceLifecycle.ERROR, last_error=str(exc))
            else:
                instance = replace(instance, lifecycle_status=InstanceLifecycle.PENDING, last_error="Docker socket unavailable")
            self.instances.upsert(instance)
            self._register_node(instance)
            config.hermes_instance_id = instance.id

        AgentHermesBindingStore().upsert(AgentHermesBinding(
            profile_id=config.profile_id,
            runtime_provider=HermesRuntimeProvider.HERMES,
            hermes_node_ids=[instance.id],
            hermes_routing_policy=HermesRoutingPolicy.PRIORITY,
            hermes_fallback_enabled=False,
            required_capabilities=["text"],
        ))
        return config, instance

    async def stop(self, instance: HermesInstance) -> HermesInstance:
        if instance.mode == HermesInstanceMode.SHARED:
            raise ContainerManagerError("共享实例不能因单个 Agent 停止")
        if instance.base_url.startswith("native://"):
            updated = replace(instance, lifecycle_status=InstanceLifecycle.STOPPED)
        else:
            updated = (
                await self.containers.stop(instance)
                if HermesContainerManager.available()
                else replace(instance, lifecycle_status=InstanceLifecycle.STOPPED)
            )
        self.instances.upsert(updated)
        self._register_node(updated)
        return updated

    async def restart(self, instance: HermesInstance) -> HermesInstance:
        if instance.base_url.startswith("native://") or self.native_default():
            if not NativeHermesRuntime.available():
                raise ContainerManagerError("Embedded Hermes runtime unavailable")
            updated = replace(
                instance,
                base_url=self._native_url(instance.id),
                lifecycle_status=InstanceLifecycle.RUNNING,
                last_error=None,
            )
        else:
            if not HermesContainerManager.available():
                raise ContainerManagerError("Docker socket unavailable")
            updated = await self.containers.restart(replace(instance, image=self.RUNTIME_IMAGE))
        self.instances.upsert(updated)
        self._register_node(updated)
        return updated

    async def remove(self, instance: HermesInstance, *, delete_data: bool = False) -> None:
        if instance.mode == HermesInstanceMode.SHARED:
            raise ContainerManagerError("不能删除默认共享实例")
        if not instance.base_url.startswith("native://") and HermesContainerManager.available():
            await self.containers.remove(instance, delete_data=delete_data)
        self.instances.delete(instance.id)
        get_hermes_store().delete(instance.id)
