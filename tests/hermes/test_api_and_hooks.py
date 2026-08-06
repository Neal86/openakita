import inspect

from fastapi import FastAPI

from openakita.agent.core import Agent
from openakita.api.server import mount_hermes_execution_routes


def test_hermes_routes_mount_once_under_api_prefix():
    app = FastAPI()
    mount_hermes_execution_routes(app)
    mount_hermes_execution_routes(app)
    paths = [getattr(route, "path", "") for route in app.routes]
    assert paths.count("/api/hermes/nodes") == 1
    assert paths.count("/api/hermes/stats") == 1
    assert paths.count("/api/hermes/ui") == 1
    assert paths.count("/api/execution/instances") == 1
    assert paths.count("/v1/chat/completions") == 1
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
