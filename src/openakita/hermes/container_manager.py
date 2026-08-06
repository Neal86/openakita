"""Restricted Docker lifecycle manager for OpenAkita-owned Hermes instances.

Only containers/volumes with the OpenAkita Hermes prefix are touched.  The
manager uses the Docker CLI so no additional Python dependency is required.
Mount /var/run/docker.sock into OpenAkita to enable dedicated instances.
"""
from __future__ import annotations

import asyncio
import json
import os
import shlex
from dataclasses import replace
from typing import Any

from .execution import HermesInstance, InstanceLifecycle


class ContainerManagerError(RuntimeError):
    pass


class HermesContainerManager:
    CONTAINER_PREFIX = "openakita-hermes-"
    VOLUME_PREFIX = "openakita_hermes_"
    ALLOWED_IMAGE_PREFIXES = ("nousresearch/hermes-agent",)

    async def _run(self, *args: str, timeout: int = 60, check: bool = True) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "docker", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            raise ContainerManagerError(f"docker command timed out: {shlex.join(args)}") from None
        stdout, stderr = out.decode(errors="replace").strip(), err.decode(errors="replace").strip()
        if check and proc.returncode != 0:
            raise ContainerManagerError(stderr or stdout or f"docker exited {proc.returncode}")
        return proc.returncode or 0, stdout, stderr

    def _validate(self, instance: HermesInstance) -> None:
        if not instance.container_name.startswith(self.CONTAINER_PREFIX):
            raise ContainerManagerError("refusing non-OpenAkita container name")
        if not instance.volume_name.startswith(self.VOLUME_PREFIX):
            raise ContainerManagerError("refusing non-OpenAkita volume name")
        if not instance.image.startswith(self.ALLOWED_IMAGE_PREFIXES):
            raise ContainerManagerError("Hermes image is not allow-listed")

    async def inspect(self, instance: HermesInstance) -> dict[str, Any]:
        self._validate(instance)
        code, stdout, _ = await self._run(
            "inspect", instance.container_name, "--format", "{{json .State}}", check=False
        )
        if code != 0 or not stdout:
            return {"exists": False, "running": False, "status": "missing"}
        try:
            state = json.loads(stdout)
        except json.JSONDecodeError:
            state = {}
        return {
            "exists": True,
            "running": bool(state.get("Running")),
            "status": state.get("Status", "unknown"),
            "health": (state.get("Health") or {}).get("Status", "unknown"),
            "error": state.get("Error") or None,
        }

    async def ensure_network(self, network: str) -> None:
        code, _, _ = await self._run("network", "inspect", network, check=False)
        if code != 0:
            await self._run("network", "create", network)

    async def create_or_start(self, instance: HermesInstance) -> HermesInstance:
        self._validate(instance)
        await self.ensure_network(instance.network)
        state = await self.inspect(instance)
        if state["exists"]:
            if not state["running"]:
                await self._run("start", instance.container_name)
            return replace(instance, lifecycle_status=InstanceLifecycle.RUNNING, last_error=None)

        await self._run("volume", "create", instance.volume_name)
        env = [
            "-e", "API_SERVER_ENABLED=true",
            "-e", "API_SERVER_HOST=0.0.0.0",
            "-e", "API_SERVER_PORT=8642",
            "-e", "OPENAI_BASE_URL=http://openakita:18900/v1",
            "-e", f"OPENAI_MODEL=agent:{instance.agent_profile_id or 'default'}",
            "-e", f"OPENAKITA_AGENT_PROFILE_ID={instance.agent_profile_id or 'default'}",
        ]
        await self._run(
            "run", "-d", "--name", instance.container_name,
            "--restart", "unless-stopped",
            "--network", instance.network,
            "--label", "openakita.managed=true",
            "--label", f"openakita.hermes.instance={instance.id}",
            "-v", f"{instance.volume_name}:/root/.hermes",
            *env,
            instance.image, "gateway", "run",
            timeout=180,
        )
        return replace(instance, lifecycle_status=InstanceLifecycle.RUNNING, last_error=None)

    async def stop(self, instance: HermesInstance) -> HermesInstance:
        self._validate(instance)
        state = await self.inspect(instance)
        if state["exists"] and state["running"]:
            await self._run("stop", "--time", "20", instance.container_name)
        return replace(instance, lifecycle_status=InstanceLifecycle.STOPPED)

    async def restart(self, instance: HermesInstance) -> HermesInstance:
        self._validate(instance)
        state = await self.inspect(instance)
        if not state["exists"]:
            return await self.create_or_start(instance)
        await self._run("restart", "--time", "20", instance.container_name, timeout=90)
        return replace(instance, lifecycle_status=InstanceLifecycle.RUNNING, last_error=None)

    async def remove(self, instance: HermesInstance, *, delete_data: bool = False) -> None:
        self._validate(instance)
        await self._run("rm", "-f", instance.container_name, check=False)
        if delete_data:
            await self._run("volume", "rm", instance.volume_name, check=False)

    async def logs(self, instance: HermesInstance, *, tail: int = 200) -> str:
        self._validate(instance)
        tail = min(max(int(tail), 1), 1000)
        _, stdout, stderr = await self._run("logs", "--tail", str(tail), instance.container_name, check=False)
        return (stdout + ("\n" + stderr if stderr else "")).strip()

    @staticmethod
    def available() -> bool:
        return os.path.exists("/var/run/docker.sock") or bool(os.environ.get("DOCKER_HOST"))
