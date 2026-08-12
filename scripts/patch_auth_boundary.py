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
        '        "/api/logs/frontend",\n',
        '        "/api/logs/frontend",\n        "/openapi.json",\n',
        "exact OpenAPI exemption",
    )
    replace_exact(
        path,
        'AUTH_EXEMPT_PREFIXES = ("/web/", "/web", "/ws/", "/docs", "/openapi.json", "/redoc", "/user-docs")\n',
        'AUTH_EXEMPT_PREFIXES = ("/web", "/ws", "/docs", "/redoc", "/user-docs")\n',
        "auth exempt prefix constants",
    )
    replace_exact(
        path,
        '''def _is_auth_exempt(path: str) -> bool:\n    """Check if the path is exempt from authentication."""\n    if path in AUTH_EXEMPT_PATHS:\n        return True\n    return any(path.startswith(prefix) for prefix in AUTH_EXEMPT_PREFIXES)\n''',
        '''def _is_auth_exempt(path: str) -> bool:\n    """Check auth exemptions using real path-segment boundaries.\n\n    A raw ``startswith`` would make ``/webhook`` inherit the exemption for\n    ``/web`` and ``/docs-private`` inherit ``/docs``. Only the exact path or a\n    slash-delimited child path is exempt.\n    """\n    if path in AUTH_EXEMPT_PATHS:\n        return True\n    return any(\n        path == prefix or path.startswith(prefix.rstrip("/") + "/")\n        for prefix in AUTH_EXEMPT_PREFIXES\n    )\n''',
        "auth exemption matcher",
    )
    replace_exact(
        path,
        '''    def verify_password(self, password: str) -> bool:\n        self._refresh_if_changed()\n        h = self._data.get("password_hash", "")\n        s = self._data.get("password_salt", "")\n        if not h or not s:\n            return False\n        return _verify_password(password, h, s)\n''',
        '''    def verify_password(self, password: str) -> bool:\n        self._refresh_if_changed()\n        with self._lock:\n            h = self._data.get("password_hash", "")\n            s = self._data.get("password_salt", "")\n        if not h or not s:\n            return False\n        return _verify_password(password, h, s)\n''',
        "password read snapshot",
    )

    test = Path("tests/api/test_auth_exemption_boundaries.py")
    test.write_text(
        '''from openakita.api.auth import _is_auth_exempt\n\n\ndef test_static_auth_exemptions_require_path_boundary():\n    assert _is_auth_exempt("/web")\n    assert _is_auth_exempt("/web/assets/app.js")\n    assert _is_auth_exempt("/docs")\n    assert _is_auth_exempt("/docs/")\n    assert _is_auth_exempt("/user-docs/guide")\n    assert _is_auth_exempt("/openapi.json")\n\n    assert not _is_auth_exempt("/webhook")\n    assert not _is_auth_exempt("/web-admin")\n    assert not _is_auth_exempt("/docs-private")\n    assert not _is_auth_exempt("/redoc-admin")\n    assert not _is_auth_exempt("/openapi.json.bak")\n    assert not _is_auth_exempt("/openapi.json/anything")\n    assert not _is_auth_exempt("/user-docs-private")\n''',
        "utf-8",
    )


if __name__ == "__main__":
    main()
