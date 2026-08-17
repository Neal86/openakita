from __future__ import annotations

import io
import zipfile

import pytest

from openakita.api.routes import wechat_desktop as route


def _zip_bytes() -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("connector.py", "print('ok')\n")
    return payload.getvalue()


def test_legacy_release_rejects_invalid_zip(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "OPENAKITA_WECHAT_CONNECTOR_DOWNLOAD_URL",
        "https://example.invalid/connector.zip",
    )
    monkeypatch.setattr(
        route.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO(b"not-a-zip"),
    )

    with pytest.raises(OSError, match="valid ZIP"):
        route._download_release_to_cache()
    assert not route._release_cache_path().exists()


def test_legacy_release_caches_valid_zip(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAKITA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "OPENAKITA_WECHAT_CONNECTOR_DOWNLOAD_URL",
        "https://example.invalid/connector.zip",
    )
    payload = _zip_bytes()
    monkeypatch.setattr(
        route.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO(payload),
    )

    cached = route._download_release_to_cache()
    assert cached.read_bytes() == payload
    with zipfile.ZipFile(cached) as archive:
        assert archive.testzip() is None
