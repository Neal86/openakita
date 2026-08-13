from pathlib import Path


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text("utf-8")
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"{label} marker changed")
    path.write_text(text.replace(old, new, 1), "utf-8")


def main() -> None:
    path = Path("deploy/hermes/shared_gateway.py")
    replace_exact(
        path,
        '''    def prune_dead(self) -> None:\n        for profile_id, child in list(self.children.items()):\n            if child.process.poll() is not None:\n                self.children.pop(profile_id, None)\n                self._dispose(child)\n''',
        '''    def prune_dead(self) -> None:\n        for profile_id, child in list(self.children.items()):\n            if child.process.poll() is not None:\n                self.children.pop(profile_id, None)\n                self._dispose(child)\n                lock = self.locks.get(profile_id)\n                if lock is not None and not lock.locked():\n                    self.locks.pop(profile_id, None)\n''',
        "prune dead child locks",
    )
    replace_exact(
        path,
        '''    def stop(self, profile_id: str) -> None:\n        child = self.children.pop(safe_id(profile_id), None)\n        if child:\n            self._dispose(child, terminate=True)\n''',
        '''    def stop(self, profile_id: str) -> None:\n        profile_id = safe_id(profile_id)\n        child = self.children.pop(profile_id, None)\n        if child:\n            self._dispose(child, terminate=True)\n        lock = self.locks.get(profile_id)\n        if lock is not None and not lock.locked():\n            self.locks.pop(profile_id, None)\n''',
        "stop child lock cleanup",
    )


if __name__ == "__main__":
    main()
