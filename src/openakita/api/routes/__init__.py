"""API route modules.

Hermes routes are nested under the existing Agent router so older server
composition code automatically exposes them without a second registration
site. Runtime hooks are installed idempotently at API startup.
"""

from . import agents, hermes, hermes_ui
from openakita.hermes.hooks import install_agent_hooks

hermes.router.include_router(hermes_ui.router)
agents.router.include_router(hermes.router)
install_agent_hooks()

__all__ = ["agents", "hermes", "hermes_ui"]
