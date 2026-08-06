"""API route package.

Route modules are mounted explicitly by :mod:`openakita.api.server`; importing
this package must not mutate unrelated routers.
"""

from openakita.hermes.hooks import install_agent_hooks

# Runtime chat hooks are process-wide and idempotent. Route mounting belongs to
# the FastAPI composition root, but installing the hooks here preserves the
# historical Agent import behavior used by desktop and tests.
install_agent_hooks()

__all__: list[str] = []
