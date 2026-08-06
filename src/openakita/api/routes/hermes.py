"""Hermes node and Agent binding API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from openakita.hermes.bindings import AgentHermesBinding, AgentHermesBindingStore
from openakita.hermes.models import HermesNode
from openakita.hermes.router import HermesRouter
from openakita.hermes.store import get_hermes_store

# This router is nested under the existing Agents router, which the server mounts
# with prefix="/api". Keep the local prefix relative to avoid /api/api/hermes.
router = APIRouter(prefix="/hermes", tags=["智能体"])


class HermesNodePayload(BaseModel):
    id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=120)
    base_url: str = Field(..., min_length=8, max_length=1000)
    api_key_env: str = Field("", max_length=200)
    enabled: bool = True
    priority: int = Field(100, ge=0)
    weight: int = Field(1, ge=1)
    capabilities: list[str] = Field(default_factory=lambda: ["text", "tools"])
    tags: list[str] = Field(default_factory=list)
    max_concurrency: int = Field(4, ge=1)
    timeout_seconds: int = Field(180, ge=1, le=3600)


class AgentBindingPayload(BaseModel):
    runtime_provider: str = "local"
    hermes_node_ids: list[str] = Field(default_factory=list)
    hermes_routing_policy: str = "priority"
    hermes_fallback_enabled: bool = True
    required_capabilities: list[str] = Field(default_factory=list)


@router.get("/nodes")
def list_nodes() -> dict:
    return {"nodes": [node.to_dict() for node in get_hermes_store().list()]}


@router.post("/nodes")
def create_node(payload: HermesNodePayload) -> dict:
    store = get_hermes_store()
    if store.get(payload.id):
        raise HTTPException(status_code=409, detail="Hermes node already exists")
    node = HermesNode(**payload.model_dump())
    store.upsert(node)
    return {"node": node.to_dict()}


@router.get("/nodes/{node_id}")
def get_node(node_id: str) -> dict:
    node = get_hermes_store().get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Hermes node not found")
    return {"node": node.to_dict()}


@router.put("/nodes/{node_id}")
def update_node(node_id: str, payload: HermesNodePayload) -> dict:
    if payload.id != node_id:
        raise HTTPException(status_code=400, detail="Node id cannot be changed")
    store = get_hermes_store()
    if store.get(node_id) is None:
        raise HTTPException(status_code=404, detail="Hermes node not found")
    node = HermesNode(**payload.model_dump())
    store.upsert(node)
    return {"node": node.to_dict()}


@router.delete("/nodes/{node_id}")
def delete_node(node_id: str) -> dict:
    if not get_hermes_store().delete(node_id):
        raise HTTPException(status_code=404, detail="Hermes node not found")
    return {"deleted": True, "id": node_id}


@router.post("/nodes/{node_id}/enable")
def enable_node(node_id: str) -> dict:
    store = get_hermes_store()
    node = store.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Hermes node not found")
    node.enabled = True
    store.upsert(node)
    return {"node": node.to_dict()}


@router.post("/nodes/{node_id}/disable")
def disable_node(node_id: str) -> dict:
    store = get_hermes_store()
    node = store.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Hermes node not found")
    node.enabled = False
    store.upsert(node)
    return {"node": node.to_dict()}


@router.post("/nodes/{node_id}/test")
async def test_node(node_id: str) -> dict:
    try:
        return await HermesRouter().test_node(node_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Hermes node not found") from None


@router.get("/stats")
def stats() -> dict:
    nodes = get_hermes_store().list()
    return {
        "total": len(nodes),
        "enabled": sum(1 for node in nodes if node.enabled),
        "available": sum(1 for node in nodes if node.available),
        "inflight": sum(node.current_inflight for node in nodes),
        "capacity": sum(node.max_concurrency for node in nodes if node.enabled),
    }


@router.get("/agents/{profile_id}")
def get_binding(profile_id: str) -> dict:
    return {"binding": AgentHermesBindingStore().get(profile_id).to_dict()}


@router.put("/agents/{profile_id}")
def update_binding(profile_id: str, payload: AgentBindingPayload) -> dict:
    try:
        binding = AgentHermesBinding(profile_id=profile_id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    known_nodes = {node.id for node in get_hermes_store().list()}
    missing = [node_id for node_id in binding.hermes_node_ids if node_id not in known_nodes]
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown Hermes nodes: {', '.join(missing)}")
    AgentHermesBindingStore().upsert(binding)
    return {"binding": binding.to_dict()}
