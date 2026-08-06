from starlette.requests import Request

from openakita.api.auth import is_private_direct_request
from openakita.api.openai_compat import convert_tools, split_system
from openakita.hermes.client import HermesClient
from openakita.hermes.models import HermesNode


def make_request(host: str, headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/chat/completions",
            "headers": headers or [],
            "client": (host, 12345),
            "server": ("openakita", 18900),
            "scheme": "http",
            "query_string": b"",
        }
    )


def test_shared_client_sends_agent_and_session_headers():
    client = HermesClient(HermesNode(id="shared", name="Shared", base_url="http://shared:8642"))
    headers = client._headers(session_id="session-1", agent_id="customer-agent")
    assert headers["X-OpenAkita-Agent-Id"] == "customer-agent"
    assert headers["X-Hermes-Session-Id"] == "session-1"


def test_private_direct_gateway_request_is_allowed():
    assert is_private_direct_request(make_request("172.20.0.3"))
    assert is_private_direct_request(make_request("127.0.0.1"))


def test_forwarded_private_request_is_rejected():
    request = make_request("172.20.0.2", [(b"x-forwarded-for", b"203.0.113.4")])
    assert not is_private_direct_request(request)


def test_public_direct_request_is_rejected():
    assert not is_private_direct_request(make_request("8.8.8.8"))


def test_openai_conversion_preserves_system_and_tools():
    system, messages = split_system([
        {"role": "system", "content": "Be useful"},
        {"role": "user", "content": "Hello"},
    ])
    tools = convert_tools([
        {"type": "function", "function": {"name": "lookup", "description": "Lookup", "parameters": {"type": "object"}}}
    ])
    assert system == "Be useful"
    assert messages[0].role == "user"
    assert tools and tools[0].name == "lookup"
