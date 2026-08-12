"""Restricted Docker lifecycle manager for OpenAkita-owned Hermes instances."""
from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import sys
from dataclasses import replace
from typing import Any

from .execution import HermesInstance, InstanceLifecycle


class ContainerManagerError(RuntimeError):
    pass


class HermesContainerManager:
    CONTAINER_PREFIX = "openakita-hermes-"
    VOLUME_PREFIX = "openakita_hermes_"
    ALLOWED_IMAGE_PREFIXES = ("openakita-hermes-runtime", "nousresearch/hermes-agent")

    async def _run(self, *args: str, timeout: int = 60, check: bool = True) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec("docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
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

    @staticmethod
    def _is_missing_container_error(message: str) -> bool:
        lowered = message.lower()
        return "no such container" in lowered or "no such object" in lowered

    @staticmethod
    def _is_missing_volume_error(message: str) -> bool:
        return "no such volume" in message.lower()

    def _validate(self, instance: HermesInstance) -> None:
        if not instance.container_name.startswith(self.CONTAINER_PREFIX):
            raise ContainerManagerError("refusing non-OpenAkita container name")
        if not instance.volume_name.startswith(self.VOLUME_PREFIX):
            raise ContainerManagerError("refusing non-OpenAkita volume name")
        if not instance.image.startswith(self.ALLOWED_IMAGE_PREFIXES):
            raise ContainerManagerError("Hermes image is not allow-listed")

    async def inspect(self, instance: HermesInstance) -> dict[str, Any]:
        self._validate(instance)
        code, stdout, stderr = await self._run(
            "inspect",
            instance.container_name,
            "--format",
            "{{json .State}}",
            check=False,
        )
        if code != 0:
            detail = stderr or stdout
            if self._is_missing_container_error(detail):
                return {"exists": False, "running": False, "status": "missing"}
            raise ContainerManagerError(
                detail or f"docker inspect exited {code} for {instance.container_name}"
            )
        if not stdout:
            raise ContainerManagerError(
                f"docker inspect returned empty state for {instance.container_name}"
            )
        try:
            state = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ContainerManagerError(
                f"docker inspect returned invalid state for {instance.container_name}"
            ) from exc
        if not isinstance(state, dict):
            raise ContainerManagerError(
                f"docker inspect returned invalid state for {instance.container_name}"
            )
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
        profile_id = instance.agent_profile_id or "default"
        env = [
            "-e", "API_SERVER_HOST=0.0.0.0",
            "-e", "API_SERVER_PORT=8642",
            "-e", "OPENAI_API_KEY=openakita-internal",
            "-e", "OPENAI_BASE_URL=http://openakita:18900/v1",
            "-e", f"OPENAI_MODEL=agent:{profile_id}",
            "-e", f"OPENAKITA_AGENT_PROFILE_ID={profile_id}",
            "-e", "HERMES_SHARED_MAX_AGENTS=1",
        ]
        await self._run(
            "run", "-d", "--name", instance.container_name,
            "--restart", "unless-stopped",
            "--network", instance.network,
            "--label", "openakita.managed=true",
            "--label", f"openakita.hermes.instance={instance.id}",
            "-v", f"{instance.volume_name}:/opt/openakita/agents",
            *env,
            instance.image,
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
        state = await self.inspect(instance)
        if state["exists"]:
            await self._run("rm", "-f", instance.container_name)
        if delete_data:
            code, stdout, stderr = await self._run(
                "volume", "inspect", instance.volume_name, check=False
            )
            if code == 0:
                await self._run("volume", "rm", instance.volume_name)
            else:
                detail = stderr or stdout
                if not self._is_missing_volume_error(detail):
                    raise ContainerManagerError(
                        detail or f"docker volume inspect exited {code} for {instance.volume_name}"
                    )

    async def logs(self, instance: HermesInstance, *, tail: int = 200) -> str:
        self._validate(instance)
        tail = min(max(int(tail), 1), 1000)
        _, stdout, stderr = await self._run("logs", "--tail", str(tail), instance.container_name, check=False)
        return (stdout + ("\n" + stderr if stderr else "")).strip()

    @staticmethod
    def available() -> bool:
        if os.path.exists("/var/run/docker.sock") or bool(os.environ.get("DOCKER_HOST")):
            return True
        if sys.platform in {"win32", "darwin"}:
            # Docker Desktop normally uses a platform-managed context/named pipe
            # and does not require DOCKER_HOST. Presence of the CLI is enough to
            # try the real operation; daemon failures are then surfaced by _run.
            return shutil.which("docker") is not None
        return False
