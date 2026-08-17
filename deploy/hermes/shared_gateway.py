#!/usr/bin/env python3
"""Multi-agent gateway for one-container / isolated-Hermes execution.

Each profile gets a dedicated Hermes child process with an ephemeral HOME and
API port. Durable Agent memory, identity, skills and configuration remain owned
by OpenAkita; the Docker runtime only keeps process/session execution state.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
import uvicorn

ROOT = Path(os.environ.get("OPENAKITA_HERMES_AGENT_ROOT", "/opt/openakita/agents")).resolve()
RUNTIME_ROOT = Path(os.environ.get("OPENAKITA_HERMES_RUNTIME_ROOT", "/tmp/openakita-hermes-runtime")).resolve()
HOST = os.environ.get("API_SERVER_HOST", "0.0.0.0")
PORT = int(os.environ.get("API_SERVER_PORT", "8642"))
CHILD_START_TIMEOUT = int(os.environ.get("HERMES_CHILD_START_TIMEOUT", "120"))
MAX_CHILDREN = int(os.environ.get("HERMES_SHARED_MAX_AGENTS", "32"))
AUTH_FILE = os.environ.get("OPENAKITA_HERMES_AUTH_FILE", "").strip()


def openakita_gateway_key() -> str:
    configured = os.environ.get("OPENAKITA_HERMES_LLM_API_KEY", "").strip()
    if configured:
        return configured
    if AUTH_FILE:
        try:
            value = Path(AUTH_FILE).read_text("utf-8").strip()
        except OSError:
            value = ""
        if value:
            return value
    raise HTTPException(
        status_code=503,
        detail="OpenAkita internal gateway token is not available yet",
    )


def safe_id(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", (value or "default").strip()).strip("-").lower()
    return (value or "default")[:64]


def free_port(profile_id: str) -> int:
    start = 10000 + int(hashlib.sha256(profile_id.encode()).hexdigest()[:4], 16) % 40000
    for port in range(start, min(start + 1000, 65000)):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no free child port")


@dataclass
class Child:
    profile_id: str
    port: int
    process: subprocess.Popen
    home: Path
    started_at: float
    log_handle: BinaryIO


class ChildManager:
    def __init__(self) -> None:
        self.children: dict[str, Child] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        ROOT.mkdir(parents=True, exist_ok=True)
        RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)

    def _dispose(self, child: Child, *, terminate: bool = False) -> None:
        try:
            if terminate and child.process.poll() is None:
                try:
                    os.killpg(child.process.pid, signal.SIGTERM)
                    child.process.wait(timeout=20)
                except Exception:
                    try:
                        os.killpg(child.process.pid, signal.SIGKILL)
                    except Exception:
                        pass
        finally:
            try:
                child.log_handle.close()
            except Exception:
                pass
            shutil.rmtree(child.home, ignore_errors=True)

    def prune_dead(self) -> None:
        for profile_id, child in list(self.children.items()):
            if child.process.poll() is not None:
                self.children.pop(profile_id, None)
                self._dispose(child)
                lock = self.locks.get(profile_id)
                if lock is not None and not lock.locked():
                    self.locks.pop(profile_id, None)

    def _drop_idle_lock(self, profile_id: str, lock: asyncio.Lock) -> None:
        current = self.locks.get(profile_id)
        if current is lock and not lock.locked() and profile_id not in self.children:
            self.locks.pop(profile_id, None)

    async def ensure(self, profile_id: str) -> Child:
        profile_id = safe_id(profile_id)
        lock = self.locks.setdefault(profile_id, asyncio.Lock())
        async with lock:
            self.prune_dead()
            existing = self.children.get(profile_id)
            if existing and existing.process.poll() is None:
                return existing
            if existing:
                self.children.pop(profile_id, None)
                self._dispose(existing)
            if len(self.children) >= MAX_CHILDREN:
                asyncio.get_running_loop().call_soon(
                    self._drop_idle_lock, profile_id, lock
                )
                raise HTTPException(status_code=503, detail="共享实例已达到最大 Agent 数")

            home = Path(tempfile.mkdtemp(prefix=f"{profile_id}-", dir=RUNTIME_ROOT)).resolve()
            if RUNTIME_ROOT not in home.parents:
                shutil.rmtree(home, ignore_errors=True)
                asyncio.get_running_loop().call_soon(
                    self._drop_idle_lock, profile_id, lock
                )
                raise HTTPException(status_code=400, detail="invalid Agent id")
            workspace = home / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            try:
                port = free_port(profile_id)
            except Exception:
                shutil.rmtree(home, ignore_errors=True)
                asyncio.get_running_loop().call_soon(
                    self._drop_idle_lock, profile_id, lock
                )
                raise
            env = os.environ.copy()
            env.update({
                "HOME": str(home),
                "HERMES_HOME": str(home / ".hermes"),
                "API_SERVER_ENABLED": "true",
                "API_SERVER_HOST": "127.0.0.1",
                "API_SERVER_PORT": str(port),
                "API_SERVER_MODEL_NAME": f"agent:{profile_id}",
                "API_SERVER_KEY": env.get("API_SERVER_KEY", "openakita-internal"),
                "OPENAI_API_KEY": openakita_gateway_key(),
                "OPENAI_BASE_URL": env.get("OPENAI_BASE_URL", "http://openakita:18900/v1"),
                "OPENAI_MODEL": f"agent:{profile_id}",
                "OPENAKITA_AGENT_PROFILE_ID": profile_id,
                "HERMES_DASHBOARD": "0",
                "HERMES_ALLOW_ROOT_GATEWAY": "1",
            })
            log_handle = open(home / "hermes.log", "ab", buffering=0)
            try:
                process = subprocess.Popen(
                    ["/opt/hermes/.venv/bin/hermes", "gateway", "run"],
                    env=env,
                    cwd=str(workspace),
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except Exception:
                log_handle.close()
                shutil.rmtree(home, ignore_errors=True)
                asyncio.get_running_loop().call_soon(
                    self._drop_idle_lock, profile_id, lock
                )
                raise
            child = Child(profile_id, port, process, home, time.time(), log_handle)
            self.children[profile_id] = child

            deadline = time.monotonic() + CHILD_START_TIMEOUT
            async with httpx.AsyncClient(timeout=3) as client:
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.children.pop(profile_id, None)
                        self._dispose(child)
                        asyncio.get_running_loop().call_soon(
                            self._drop_idle_lock, profile_id, lock
                        )
                        raise HTTPException(
                            status_code=502, detail=f"Hermes Agent {profile_id} 启动失败"
                        )
                    try:
                        response = await client.get(f"http://127.0.0.1:{port}/health")
                        if response.is_success:
                            return child
                    except Exception:
                        pass
                    await asyncio.sleep(1)
            self.stop(profile_id)
            asyncio.get_running_loop().call_soon(
                self._drop_idle_lock, profile_id, lock
            )
            raise HTTPException(status_code=504, detail=f"Hermes Agent {profile_id} 启动超时")

    def stop(self, profile_id: str) -> None:
        profile_id = safe_id(profile_id)
        child = self.children.pop(profile_id, None)
        if child:
            self._dispose(child, terminate=True)
        lock = self.locks.get(profile_id)
        if lock is not None and not lock.locked():
            self.locks.pop(profile_id, None)

    def shutdown(self) -> None:
        for profile_id in list(self.children):
            self.stop(profile_id)


manager = ChildManager()
app = FastAPI(title="OpenAkita Hermes Shared Gateway")


def agent_id(request: Request) -> str:
    value = request.headers.get("X-OpenAkita-Agent-Id") or request.headers.get("X-Hermes-Agent-Id")
    return safe_id(value or "default")


@app.get("/health")
async def health() -> dict[str, Any]:
    manager.prune_dead()
    running = sum(1 for child in manager.children.values() if child.process.poll() is None)
    return {"status": "ok", "mode": "shared", "running_agents": running, "max_agents": MAX_CHILDREN}


@app.get("/agents")
async def agents() -> dict[str, Any]:
    manager.prune_dead()
    return {
        "agents": [
            {"profile_id": c.profile_id, "pid": c.process.pid, "port": c.port, "running": c.process.poll() is None}
            for c in manager.children.values()
        ]
    }


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request):
    child = await manager.ensure(agent_id(request))
    body = await request.body()
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length", "connection"}
    }
    url = f"http://127.0.0.1:{child.port}/v1/{path}"
    try:
        parsed = json.loads(body) if body else {}
    except json.JSONDecodeError:
        parsed = {}
    is_stream = "text/event-stream" in request.headers.get("accept", "") or parsed.get("stream") is True

    if is_stream:
        client = httpx.AsyncClient(timeout=None)
        downstream_request = client.build_request(
            request.method,
            url,
            content=body,
            headers=headers,
            params=request.query_params,
        )
        try:
            downstream = await client.send(downstream_request, stream=True)
        except Exception:
            await client.aclose()
            raise
        if downstream.status_code >= 400:
            payload = await downstream.aread()
            status = downstream.status_code
            content_type = downstream.headers.get("content-type")
            await downstream.aclose()
            await client.aclose()
            return Response(payload, status_code=status, media_type=content_type)

        async def stream():
            try:
                async for data in downstream.aiter_raw():
                    yield data
            finally:
                await downstream.aclose()
                await client.aclose()

        return StreamingResponse(
            stream(),
            media_type=downstream.headers.get("content-type", "text/event-stream"),
            headers={"X-OpenAkita-Agent-Id": child.profile_id},
        )

    async with httpx.AsyncClient(timeout=None) as client:
        response = await client.request(request.method, url, content=body, headers=headers, params=request.query_params)
    excluded = {"content-encoding", "transfer-encoding", "connection", "content-length"}
    outgoing = {key: value for key, value in response.headers.items() if key.lower() not in excluded}
    outgoing["X-OpenAkita-Agent-Id"] = child.profile_id
    return Response(
        response.content,
        status_code=response.status_code,
        headers=outgoing,
        media_type=response.headers.get("content-type"),
    )


@app.on_event("shutdown")
def shutdown() -> None:
    manager.shutdown()


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
