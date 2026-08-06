"""Atomic JSON persistence for Hermes nodes."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from openakita.utils.atomic_io import atomic_json_write

from .models import HermesNode


class HermesNodeStore:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            try:
                from openakita.config import settings

                path = Path(settings.project_root) / "data" / "hermes_nodes.json"
            except Exception:
                path = Path.cwd() / "data" / "hermes_nodes.json"
        self.path = Path(path)
        self._lock = threading.RLock()

    def _read_unlocked(self) -> list[HermesNode]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        rows = payload.get("nodes", payload if isinstance(payload, list) else [])
        return [HermesNode.from_dict(row) for row in rows if isinstance(row, dict)]

    def _write_unlocked(self, nodes: list[HermesNode]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(self.path, {"version": 1, "nodes": [n.to_dict() for n in nodes]})

    def list(self) -> list[HermesNode]:
        with self._lock:
            return self._read_unlocked()

    def get(self, node_id: str) -> HermesNode | None:
        with self._lock:
            return next((node for node in self._read_unlocked() if node.id == node_id), None)

    def save_all(self, nodes: list[HermesNode]) -> None:
        with self._lock:
            self._write_unlocked(nodes)

    def upsert(self, node: HermesNode) -> HermesNode:
        # Keep the complete read-modify-write transaction under one lock.
        # Without this, simultaneous requests could both read the same old
        # snapshot and the later writer would silently discard the earlier one.
        with self._lock:
            nodes = self._read_unlocked()
            for index, existing in enumerate(nodes):
                if existing.id == node.id:
                    nodes[index] = node
                    break
            else:
                nodes.append(node)
            self._write_unlocked(nodes)
            return node

    def delete(self, node_id: str) -> bool:
        with self._lock:
            nodes = self._read_unlocked()
            kept = [node for node in nodes if node.id != node_id]
            if len(kept) == len(nodes):
                return False
            self._write_unlocked(kept)
            return True


_default_store: HermesNodeStore | None = None
_default_store_lock = threading.Lock()


def get_hermes_store() -> HermesNodeStore:
    global _default_store
    if _default_store is None:
        with _default_store_lock:
            if _default_store is None:
                _default_store = HermesNodeStore()
    return _default_store
