from pathlib import Path


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text("utf-8")
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"{label} marker changed")
    path.write_text(text.replace(old, new, 1), "utf-8")


def main() -> None:
    path = Path("src/openakita/api/auth.py")
    replace_exact(
        path,
        '        self._file_lock = FileLock(str(self._path) + ".lock")\n        self._load()\n',
        '        self._file_lock = FileLock(str(self._path) + ".lock")\n        self._disk_version: tuple[int, int] | None = None\n        self._load()\n',
        "disk version init",
    )
    replace_exact(
        path,
        '''    def _save_locked(self) -> None:\n        atomic_json_write(\n            self._path,\n            self._data,\n            backup=True,\n            fsync=True,\n            allow_fallback=False,\n        )\n''',
        '''    def _stat_disk_version(self) -> tuple[int, int] | None:\n        try:\n            stat = self._path.stat()\n        except OSError:\n            return None\n        return stat.st_mtime_ns, stat.st_size\n\n    def _save_locked(self) -> None:\n        atomic_json_write(\n            self._path,\n            self._data,\n            backup=True,\n            fsync=True,\n            allow_fallback=False,\n        )\n        self._disk_version = self._stat_disk_version()\n''',
        "save disk version",
    )
    replace_exact(
        path,
        '''            if needs_save:\n                self._data["updated_at"] = time.strftime(\n                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()\n                )\n                self._save_locked()\n\n    def _refresh_for_mutation_locked(self) -> None:\n        latest = self._read_disk_locked()\n        if latest:\n            self._data = latest\n''',
        '''            if needs_save:\n                self._data["updated_at"] = time.strftime(\n                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()\n                )\n                self._save_locked()\n            else:\n                self._disk_version = self._stat_disk_version()\n\n    def _refresh_for_mutation_locked(self) -> None:\n        latest = self._read_disk_locked()\n        if latest:\n            self._data = latest\n        self._disk_version = self._stat_disk_version()\n\n    def _refresh_if_changed(self) -> None:\n        observed = self._stat_disk_version()\n        if observed == self._disk_version:\n            return\n        with self._lock, self._file_lock:\n            observed = self._stat_disk_version()\n            if observed == self._disk_version:\n                return\n            latest = self._read_disk_locked()\n            if latest:\n                self._data = latest\n            self._disk_version = self._stat_disk_version()\n''',
        "live reload helpers",
    )

    replacements = [
        (
            '''    @property\n    def jwt_secret(self) -> str:\n        return self._data["jwt_secret"]\n''',
            '''    @property\n    def jwt_secret(self) -> str:\n        self._refresh_if_changed()\n        return self._data["jwt_secret"]\n''',
            "jwt_secret reload",
        ),
        (
            '''    @property\n    def token_version(self) -> int:\n        return self._data.get("token_version", 1)\n''',
            '''    @property\n    def token_version(self) -> int:\n        self._refresh_if_changed()\n        return self._data.get("token_version", 1)\n''',
            "token_version reload",
        ),
        (
            '''    @property\n    def data_epoch(self) -> str:\n        return self._data.get("data_epoch", "")\n''',
            '''    @property\n    def data_epoch(self) -> str:\n        self._refresh_if_changed()\n        return self._data.get("data_epoch", "")\n''',
            "data_epoch reload",
        ),
        (
            '''    @property\n    def password_hint(self) -> str:\n        return self._data.get("password_plain_hint", "")\n''',
            '''    @property\n    def password_hint(self) -> str:\n        self._refresh_if_changed()\n        return self._data.get("password_plain_hint", "")\n''',
            "password_hint reload",
        ),
        (
            '''    def verify_password(self, password: str) -> bool:\n        h = self._data.get("password_hash", "")\n''',
            '''    def verify_password(self, password: str) -> bool:\n        self._refresh_if_changed()\n        h = self._data.get("password_hash", "")\n''',
            "verify_password reload",
        ),
        (
            '''    @property\n    def password_user_set(self) -> bool:\n        return self._data.get("password_user_set", False)\n''',
            '''    @property\n    def password_user_set(self) -> bool:\n        self._refresh_if_changed()\n        return self._data.get("password_user_set", False)\n''',
            "password_user_set reload",
        ),
        (
            '''        return bool(self._data.get("password_hash")) and bool(self._data.get("password_salt"))\n''',
            '''        self._refresh_if_changed()\n        return bool(self._data.get("password_hash")) and bool(self._data.get("password_salt"))\n''',
            "has_password_set reload",
        ),
    ]
    for old, new, label in replacements:
        replace_exact(path, old, new, label)

    test = Path("tests/api/test_web_access_persistence.py")
    text = test.read_text("utf-8")
    addition = '''\n\ndef test_running_config_observes_external_password_reset(tmp_path: Path):\n    server = WebAccessConfig(tmp_path)\n    server.change_password("server-password")\n    access_token = server.create_access_token()\n\n    cli = WebAccessConfig(tmp_path)\n    cli.clear_password()\n\n    assert not server.has_password_set\n    assert not server.verify_password("server-password")\n    assert not server.validate_access_token(access_token)\n\n\ndef test_running_config_observes_external_password_change(tmp_path: Path):\n    server = WebAccessConfig(tmp_path)\n    server.change_password("old-password")\n\n    other = WebAccessConfig(tmp_path)\n    other.change_password("new-password")\n\n    assert server.verify_password("new-password")\n    assert not server.verify_password("old-password")\n'''
    if "test_running_config_observes_external_password_reset" not in text:
        test.write_text(text + addition, "utf-8")


if __name__ == "__main__":
    main()
