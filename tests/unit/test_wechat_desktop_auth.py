from __future__ import annotations

from openakita.api.auth import _is_auth_exempt


def test_only_connector_pair_redemption_is_auth_exempt() -> None:
    assert _is_auth_exempt("/api/wechat-desktop/pair") is True
    assert _is_auth_exempt("/api/wechat-desktop/pairing-code") is False
    assert _is_auth_exempt("/api/wechat-desktop/nodes") is False
    assert _is_auth_exempt("/api/wechat-desktop/nodes/node-1") is False
