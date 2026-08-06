"""Execution-mode reconciliation between Agent config, instances and router nodes."""
from __future__ import annotations

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
from .store import get_hermes_store


class HermesLifecycleService:
    SHARED_ID = "shared"

    def __init__(self) -> None:
        self.instances = HermesInstanceStore()
        self.execution = None
        self.containers = HermesContainerManager()
        self.isolation = HermesIsolationManager()

    def ensure_shared(self) -> HermesInstance:
        instance = self.instances.get(self.SHARED_ID)
        if instance is None:
            instance = HermesInstance(
                id=self.SHARED_ID,
                name="Hermes 共享实例",
                mode=HermesInstanceMode.SHARED,
                container_name="openakita-hermes-shared",
                volume_name="openakita_hermes_shared_data",
                base_url="http://openakita-hermes-shared:8642",
                lifecycle_status=InstanceLifecycle.RUNNING,
                max_concurrency=16,
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
            "capabilities": ["text", "tools", "sub_agents"],
            "tags": [instance.mode.value],
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
            AgentHermesBindingStore().upsert(AgentHermesBinding(profile_id=config.profile_id, runtime_provider=HermesRuntimeProvider.LOCAL))
            return config, None

        paths = self.isolation.ensure(config.profile_id, metadata=profile_metadata or config.to_dict())
        if config.hermes_instance_mode == HermesInstanceMode.SHARED:
            instance = self.ensure_shared()
        else:
            instance_id = config.hermes_instance_id or f"dedicated-{config.profile_id}"
            instance = self.instances.get(instance_id) or HermesInstance(
                id=instance_id,
                name=f"{config.profile_id} 专属 Hermes",
                mode=HermesInstanceMode.DEDICATED,
                agent_profile_id=config.profile_id,
                max_concurrency=4,
            )
            if HermesContainerManager.available():
                try:
                    instance = await self.containers.create_or_start(instance)
                except Exception as exc:
                    instance = replace(instance, lifecycle_status=InstanceLifecycle.ERROR, last_error=str(exc))
            else:
                # Saved as pending so a deployment with Docker socket can reconcile it.
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
        updated = await self.containers.stop(instance) if HermesContainerManager.available() else replace(instance, lifecycle_status=InstanceLifecycle.STOPPED)
        self.instances.upsert(updated)
        self._register_node(updated)
        return updated

    async def restart(self, instance: HermesInstance) -> HermesInstance:
        if not HermesContainerManager.available():
            raise ContainerManagerError("Docker socket unavailable")
        updated = await self.containers.restart(instance)
        self.instances.upsert(updated)
        self._register_node(updated)
        return updated

    async def remove(self, instance: HermesInstance, *, delete_data: bool = False) -> None:
        if instance.mode == HermesInstanceMode.SHARED:
            raise ContainerManagerError("不能删除默认共享实例")
        if HermesContainerManager.available():
            await self.containers.remove(instance, delete_data=delete_data)
        self.instances.delete(instance.id)
        get_hermes_store().delete(instance.id)
