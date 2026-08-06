"""API route modules.

Hermes routes are nested under the existing Agent router so older server
composition code automatically exposes them without a second registration
site. This keeps plugin/desktop builds that import ``routes.agents`` working.
"""

from . import agents, hermes

agents.router.include_router(hermes.router)

__all__ = ["agents", "hermes"]
