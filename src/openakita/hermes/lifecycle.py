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
        requested = os.environ.get("OPENAKITA_HERMES_RUNTIME", "").strip().lower()
        if requested in {"docker", "container", "remote"}:
            return False
        if requested in {"native", "embedded", "desktop"}:
            return True
        return sys.platform == "win32"

    @staticmethod
    def _native_url(instance_id: str) -> str:
        return f"native://{instance_id}"

    @staticmethod
    def _default_container_url(instance: HermesInstance) -> str:
        return f"http://{instance.container_name}:8642"

    @classmethod
    def is_native(cls, instance: HermesInstance) -> bool:
        """Return whether this *instance* explicitly uses the embedded runtime.

        Platform defaults decide how a newly-created/default instance is
        initialized; they must not override an explicitly persisted HTTP(S)
        endpoint.  Otherwise Windows would silently turn remote/container
        Hermes instances into ``native://`` instances on read/start/stop.
        """
        return isinstance(instance.base_url, str) and instance.base_url.startswith("native://")

    @classmethod
    def _should_migrate_default_to_native(cls, instance: HermesInstance) -> bool:
        if not cls.native_default() or cls.is_native(instance):
            return False
        base_url = (instance.base_url or "").rstrip("/")
        default_url = cls._default_container_url(instance).rstrip("/")
        return not base_url or base_url == default_url

    def normalize_instance(self, instance: HermesInstance) -> HermesInstance:
        if not self._should_migrate_default_to_native(instance):
            return instance
        normalized = replace(instance, base_url=self._native_url(instance.id))
        if instance.enabled:
            normalized = self._native_state(normalized)
        self.instances.upsert(normalized)
        self._register_node(normalized)
        return normalized

    def _native_state(self, instance: HermesInstance) -> HermesInstance:
        available = NativeHermesRuntime.available()
        if not available:
            return replace(instance, base_url=self._native_url(instance.id), lifecycle_status=InstanceLifecycle.ERROR, health_status="unhealthy", last_error="Embedded Hermes runtime unavailable")
        if not instance.enabled:
            return replace(instance, base_url=self._native_url(instance.id), lifecycle_status=InstanceLifecycle.STOPPED, health_status="disabled", last_error=None)
        return replace(instance, base_url=self._native_url(instance.id), lifecycle_status=InstanceLifecycle.RUNNING, health_status="healthy", last_error=None)

    def ensure_shared(self) -> HermesInstance:
        instance = self.instances.get(self.SHARED_ID)
        if instance is None:
            use_native = self.native_default()
            instance = HermesInstance(
                id=self.SHARED_ID,
                name="Hermes 共享实例",
                mode=HermesInstanceMode.SHARED,
                image=self.RUNTIME_IMAGE,
                container_name="openakita-hermes-shared",
                volume_name="openakita_hermes_shared_data",
                base_url=self._native_url(self.SHARED_ID) if use_native else "http://openakita-hermes-shared:8642",
                lifecycle_status=InstanceLifecycle.PENDING,
                max_concurrency=16,
            )
        elif self._should_migrate_default_to_native(instance):
            instance = replace(instance, base_url=self._native_url(instance.id))

        if self.is_native(instance):
            instance = self._native_state(replace(instance, image=self.RUNTIME_IMAGE))
        else:
            instance = replace(instance, image=self.RUNTIME_IMAGE)
        self.instances.upsert(instance)
        self._register_node(instance)
        return instance

    def _register_node(self, instance: HermesInstance) -> None:
        node = get_hermes_store().get(instance.id)
        payload = {
            "id": instance.id,
            "name": instance.name,
            "base_url": instance.base_url,
            "enabled": instance.enabled and instance.lifecycle_status == InstanceLifecycle.RUNNING,
            "priority": 10 if instance.mode == HermesInstanceMode.DEDICATED else 100,
            "weight": 1,
            "capabilities": ["text", "tools", "skills", "memory", "sub_agents", "mcp"],
            "tags": [instance.mode.value, "native" if self.is_native(instance) else "container"],
            "max_concurrency": instance.max_concurrency,
            "timeout_seconds": 300,
        }
        if node is not None:
            payload.update({
                "health_status": instance.health_status if self.is_native(instance) else node.health_status,
                "consecutive_failures": node.consecutive_failures,
                "last_success_at": node.last_success_at,
                "last_error": instance.last_error or node.last_error,
                "current_inflight": node.current_inflight,
            })
        get_hermes_store().upsert(HermesNode(**payload))

    async def apply(self, config: AgentExecutionConfig, *, profile_metadata: dict | None = None) -> tuple[AgentExecutionConfig, HermesInstance | None]:
        if config.execution_mode == ExecutionMode.NATIVE:
            # Native execution must not retain a previous Hermes instance id.
            # Otherwise instance deletion sees the stale id as an active binding
            # even though the Agent has already switched back to OpenAkita native.
            config.hermes_instance_id = None
            AgentHermesBindingStore().upsert(AgentHermesBinding(profile_id=config.profile_id, runtime_provider=HermesRuntimeProvider.LOCAL))
            return config, None

        self.isolation.ensure(config.profile_id, metadata=profile_metadata or config.to_dict())
        if config.hermes_instance_mode == HermesInstanceMode.SHARED:
            instance = self.ensure_shared()
            config.hermes_instance_id = instance.id
        else:
            instance_id = config.hermes_instance_id or f"dedicated-{config.profile_id}"
            existing = self.instances.get(instance_id)
            instance = existing or HermesInstance(
                id=instance_id,
                name=f"{config.profile_id} 专属 Hermes",
                mode=HermesInstanceMode.DEDICATED,
                image=self.RUNTIME_IMAGE,
                agent_profile_id=config.profile_id,
                max_concurrency=4,
                base_url=self._native_url(instance_id) if self.native_default() else "",
            )
            instance = replace(instance, image=self.RUNTIME_IMAGE)
            if existing is not None and self._should_migrate_default_to_native(instance):
                instance = replace(instance, base_url=self._native_url(instance.id))

            if self.is_native(instance):
                instance = self._native_state(instance)
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

    async def start(self, instance: HermesInstance) -> HermesInstance:
        instance = self.normalize_instance(instance)
        if self.is_native(instance):
            if not NativeHermesRuntime.available():
                raise ContainerManagerError("Embedded Hermes runtime unavailable")
            updated = self._native_state(replace(instance, enabled=True, base_url=self._native_url(instance.id)))
        else:
            if not HermesContainerManager.available():
                raise ContainerManagerError("Docker socket unavailable")
            updated = await self.containers.create_or_start(replace(instance, enabled=True, image=self.RUNTIME_IMAGE))
        self.instances.upsert(updated)
        self._register_node(updated)
        return updated

    async def stop(self, instance: HermesInstance) -> HermesInstance:
        instance = self.normalize_instance(instance)
        if self.is_native(instance):
            updated = replace(instance, enabled=False, base_url=self._native_url(instance.id), lifecycle_status=InstanceLifecycle.STOPPED, health_status="disabled", last_error=None)
        else:
            if instance.mode == HermesInstanceMode.SHARED:
                raise ContainerManagerError("共享容器实例不能在这里停止")
            if not HermesContainerManager.available():
                raise ContainerManagerError(
                    "Docker socket unavailable; cannot verify or stop Hermes container"
                )
            updated = await self.containers.stop(instance)
        self.instances.upsert(updated)
        self._register_node(updated)
        return updated

    async def restart(self, instance: HermesInstance) -> HermesInstance:
        instance = self.normalize_instance(instance)
        if self.is_native(instance):
            if not NativeHermesRuntime.available():
                raise ContainerManagerError("Embedded Hermes runtime unavailable")
            updated = self._native_state(replace(instance, enabled=True, base_url=self._native_url(instance.id)))
        else:
            if not HermesContainerManager.available():
                raise ContainerManagerError("Docker socket unavailable")
            updated = await self.containers.restart(replace(instance, enabled=True, image=self.RUNTIME_IMAGE))
        self.instances.upsert(updated)
        self._register_node(updated)
        return updated

    async def remove(self, instance: HermesInstance, *, delete_data: bool = False) -> None:
        if instance.mode == HermesInstanceMode.SHARED:
            raise ContainerManagerError("不能删除默认共享实例")
        if not self.is_native(instance):
            if not HermesContainerManager.available():
                raise ContainerManagerError(
                    "Docker socket unavailable; cannot safely remove Hermes container"
                )
            await self.containers.remove(instance, delete_data=delete_data)
        self.instances.delete(instance.id)
        get_hermes_store().delete(instance.id)
