"""Atomic JSON persistence for Hermes nodes."""

from __future__ import annotations

import threading
from pathlib import Path

from filelock import FileLock

from openakita.utils.atomic_io import atomic_json_write, read_json_safe

from .models import HermesNode
from .paths import hermes_data_path


class HermesNodeStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or hermes_data_path("hermes_nodes.json"))
        self._lock = threading.RLock()
        self._file_lock = FileLock(str(self.path) + ".lock")

    def _read_unlocked(self) -> list[HermesNode]:
        payload = read_json_safe(self.path)
        if isinstance(payload, list):
            raw_rows = payload
        elif isinstance(payload, dict):
            raw_rows = payload.get("nodes", [])
        else:
            return []
        if not isinstance(raw_rows, list):
            return []
        nodes: list[HermesNode] = []
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            try:
                nodes.append(HermesNode.from_dict(row))
            except (AttributeError, TypeError, ValueError):
                # Treat one malformed persisted row as isolated corruption.
                # HermesNode.__post_init__ may raise AttributeError when a field
                # that must be a string (for example base_url) was stored with
                # another JSON type by an older/broken writer.
                continue
        return nodes

    def _write_unlocked(self, nodes: list[HermesNode]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(
            self.path,
            {"version": 1, "nodes": [node.to_dict() for node in nodes]},
        )

    def list(self) -> list[HermesNode]:
        with self._lock, self._file_lock:
            return self._read_unlocked()

    def get(self, node_id: str) -> HermesNode | None:
        with self._lock, self._file_lock:
            return next(
                (node for node in self._read_unlocked() if node.id == node_id),
                None,
            )

    def save_all(self, nodes: list[HermesNode]) -> None:
        with self._lock, self._file_lock:
            self._write_unlocked(nodes)

    def upsert(self, node: HermesNode) -> HermesNode:
        with self._lock, self._file_lock:
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
        with self._lock, self._file_lock:
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
