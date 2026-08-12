"""API route package.

Route modules are mounted explicitly by :mod:`openakita.api.server`; importing
this package must not mutate unrelated routers.
"""

from openakita.hermes.hooks import install_agent_hooks

# Runtime chat hooks are process-wide and idempotent. Route mounting belongs to
# the FastAPI composition root, but installing the hooks here preserves the
# historical Agent import behavior used by desktop and tests.
install_agent_hooks()

# ``WechatDesktopPanel`` persists desktop Connector bots through the shared
# /api/agents/bots CRUD using ``type=wechat_desktop`` and the channel registry
# has a first-class adapter with the same type. Keep the Agents API allow-list
# aligned here during route-package initialization so create/update requests do
# not reject a supported built-in adapter. This assignment is intentionally
# limited to metadata; it does not mount or mutate any router.
from . import agents as _agents  # noqa: E402

_agents.VALID_BOT_TYPES = frozenset((*_agents.VALID_BOT_TYPES, "wechat_desktop"))

__all__: list[str] = []
