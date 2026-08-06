"""API route modules and Hermes execution integration."""

from . import agents, execution_instances, hermes, hermes_ui, llm_gateway
from openakita.hermes.hooks import install_agent_hooks

# agents.router is mounted at the application root. Apply the public prefixes
# directly here so route inspection, OpenAPI and tests all see one canonical path.
hermes.router.include_router(hermes_ui.router)
agents.router.include_router(hermes.router, prefix="/api")
agents.router.include_router(execution_instances.router)
agents.router.include_router(llm_gateway.router)

install_agent_hooks()

__all__ = ["agents", "execution_instances", "hermes", "hermes_ui", "llm_gateway"]
