from openakita.api.auth import _is_auth_exempt


def test_static_auth_exemptions_require_path_boundary():
    assert _is_auth_exempt("/web")
    assert _is_auth_exempt("/web/assets/app.js")
    assert _is_auth_exempt("/docs")
    assert _is_auth_exempt("/docs/")
    assert _is_auth_exempt("/user-docs/guide")
    assert _is_auth_exempt("/openapi.json")

    assert not _is_auth_exempt("/webhook")
    assert not _is_auth_exempt("/web-admin")
    assert not _is_auth_exempt("/docs-private")
    assert not _is_auth_exempt("/redoc-admin")
    assert not _is_auth_exempt("/openapi.json.bak")
    assert not _is_auth_exempt("/openapi.json/anything")
    assert not _is_auth_exempt("/user-docs-private")
