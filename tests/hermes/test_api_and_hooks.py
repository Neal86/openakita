import inspect

from openakita.api.routes import agents
from openakita.agent.core import Agent


def test_hermes_routes_mount_once_under_api_prefix():
    paths = {getattr(route, "path", "") for route in agents.router.routes}
    assert "/api/hermes/nodes" in paths
    assert "/api/hermes/stats" in paths
    assert "/api/hermes/ui" in paths
    assert "/api/execution/instances" in paths
    assert "/v1/chat/completions" in paths
    assert not any(path.startswith("/api/api/") for path in paths)


def test_agent_chat_hooks_are_installed_idempotently():
    chat = getattr(Agent, "chat_with_session", None)
    stream = getattr(Agent, "chat_with_session_stream", None)
    if chat is not None:
        assert getattr(chat, "_hermes_wrapped", False)
        assert inspect.iscoroutinefunction(chat)
    if stream is not None:
        assert getattr(stream, "_hermes_wrapped", False)
        assert inspect.isasyncgenfunction(stream)
