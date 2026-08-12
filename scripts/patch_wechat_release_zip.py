from pathlib import Path


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text("utf-8")
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"{label} marker changed")
    path.write_text(text.replace(old, new, 1), "utf-8")


def main() -> None:
    route = Path("src/openakita/api/routes/wechat_desktop.py")
    replace_exact(
        route,
        "import urllib.error\nimport urllib.request\nfrom collections import defaultdict\n",
        "import urllib.error\nimport urllib.request\nimport zipfile\nfrom collections import defaultdict\n",
        "zipfile import",
    )
    replace_exact(
        route,
        '''        if temp.stat().st_size <= 0:\n            raise OSError("downloaded connector package is empty")\n        os.replace(temp, cache)\n        return cache\n''',
        '''        if temp.stat().st_size <= 0:\n            raise OSError("downloaded connector package is empty")\n        try:\n            with zipfile.ZipFile(temp) as archive:\n                if not archive.namelist():\n                    raise OSError("downloaded connector package has no files")\n                bad_member = archive.testzip()\n                if bad_member is not None:\n                    raise OSError(\n                        f"downloaded connector package failed CRC validation: {bad_member}"\n                    )\n        except zipfile.BadZipFile as exc:\n            raise OSError("downloaded connector package is not a valid ZIP archive") from exc\n        os.replace(temp, cache)\n        return cache\n''',
        "legacy release validation",
    )
    test = Path("tests/wechat_desktop/test_release_download.py")
    test.write_text(
        '''from __future__ import annotations\n\nimport io\nimport zipfile\n\nimport pytest\n\nfrom openakita.api.routes import wechat_desktop as route\n\n\ndef _zip_bytes() -> bytes:\n    payload = io.BytesIO()\n    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:\n        archive.writestr("connector.py", "print('ok')\\n")\n    return payload.getvalue()\n\n\ndef test_legacy_release_rejects_invalid_zip(tmp_path, monkeypatch):\n    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(tmp_path))\n    monkeypatch.setenv(\n        "OPENAKITA_WECHAT_CONNECTOR_DOWNLOAD_URL",\n        "https://example.invalid/connector.zip",\n    )\n    monkeypatch.setattr(\n        route.urllib.request,\n        "urlopen",\n        lambda *_args, **_kwargs: io.BytesIO(b"not-a-zip"),\n    )\n\n    with pytest.raises(OSError, match="valid ZIP"):\n        route._download_release_to_cache()\n    assert not route._release_cache_path().exists()\n\n\ndef test_legacy_release_caches_valid_zip(tmp_path, monkeypatch):\n    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(tmp_path))\n    monkeypatch.setenv(\n        "OPENAKITA_WECHAT_CONNECTOR_DOWNLOAD_URL",\n        "https://example.invalid/connector.zip",\n    )\n    payload = _zip_bytes()\n    monkeypatch.setattr(\n        route.urllib.request,\n        "urlopen",\n        lambda *_args, **_kwargs: io.BytesIO(payload),\n    )\n\n    cached = route._download_release_to_cache()\n    assert cached.read_bytes() == payload\n    with zipfile.ZipFile(cached) as archive:\n        assert archive.testzip() is None\n''',
        "utf-8",
    )


if __name__ == "__main__":
    main()
