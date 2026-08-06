"""API route modules and Hermes execution integration."""

from fastapi import APIRouter

from . import agents, execution_instances, hermes, hermes_ui, llm_gateway
from openakita.hermes.hooks import install_agent_hooks

# Existing Hermes route definitions are relative (/hermes).  Mount them through
# an /api wrapper because agents.router itself is mounted at the application root.
_api = APIRouter(prefix="/api")
hermes.router.include_router(hermes_ui.router)
_api.include_router(hermes.router)
agents.router.include_router(_api)

# New execution routes already carry their public /api prefix.  The LLM gateway
# intentionally lives at /v1 for OpenAI-compatible Hermes provider settings.
agents.router.include_router(execution_instances.router)
agents.router.include_router(llm_gateway.router)

install_agent_hooks()

__all__ = ["agents", "execution_instances", "hermes", "hermes_ui", "llm_gateway"]
