from starlette.requests import Request
from starlette.websockets import WebSocket

from openakita.api.auth import is_trusted_local
from openakita.api.routes.websocket import _is_trusted_local_ws


def _request(headers=None):
    return Request({"type": "http", "method": "GET", "path": "/api/health", "headers": headers or [], "client": ("127.0.0.1", 1234), "server": ("localhost", 18900), "scheme": "http", "query_string": b""})


def _ws(headers=None):
    return WebSocket({"type": "websocket", "path": "/ws/events", "headers": headers or [], "client": ("127.0.0.1", 1234), "server": ("localhost", 18900), "scheme": "ws", "query_string": b"", "subprotocols": []}, receive=lambda: None, send=lambda message: None)


def test_forwarded_loopback_http_is_not_trusted_local():
    assert is_trusted_local(_request())
    assert not is_trusted_local(_request([(b"x-forwarded-for", b"203.0.113.10")]))
    assert not is_trusted_local(_request([(b"forwarded", b"for=203.0.113.10")]))


def test_forwarded_loopback_websocket_is_not_trusted_local():
    assert _is_trusted_local_ws(_ws())
    assert not _is_trusted_local_ws(_ws([(b"x-forwarded-for", b"203.0.113.10")]))
    assert not _is_trusted_local_ws(_ws([(b"forwarded", b"for=203.0.113.10")]))
