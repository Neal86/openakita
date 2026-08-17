import inspect

from fastapi import FastAPI

from openakita.agent.core import Agent
from openakita.api.server import mount_hermes_execution_routes


def test_hermes_routes_mount_once_under_api_prefix():
    app = FastAPI()
    mount_hermes_execution_routes(app)
    mount_hermes_execution_routes(app)
    paths = app.openapi()["paths"]
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
