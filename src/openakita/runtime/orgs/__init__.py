"""DEPRECATED: import from ``openakita.orgs`` instead.

Backward-compat shim during P-RC-10 transition. Re-exports everything
from ``openakita.orgs.*`` so ``from openakita.runtime.orgs.X import Y``
keeps working (122 of 124 RECON-strict sites use submodule form, so the
24 siblings are also installed in ``sys.modules`` under the legacy path).
Removed in P10.6.
"""
from __future__ import annotations

import sys
import warnings

warnings.warn(
    "openakita.runtime.orgs is deprecated; import from openakita.orgs instead. "
    "This shim will be removed in P-RC-10 P10.6.",
    DeprecationWarning,
    stacklevel=2,
)

# Umbrella re-export: ``from openakita.runtime.orgs import OrgManager`` etc.
from openakita import orgs as _orgs  # noqa: E402,F401
from openakita.orgs import *  # noqa: E402,F401,F403

# Submodule aliases (24 siblings; RECON section 1 ordering).
# Python does not forward package submodule lookups, so each is registered
# under the legacy dotted path via ``sys.modules``.
_SUBMODULES: tuple[str, ...] = (
    "blackboard", "command_models", "command_service", "manager",
    "memory_models", "node_scheduler", "org_models", "project_models",
    "project_store", "runtime", "scheduler_models", "sqlite_store", "store",
    "_org_layout", "_runtime_agent_pipeline", "_runtime_dispatch",
    "_runtime_event_bus", "_runtime_event_store", "_runtime_lifecycle",
    "_runtime_node_lifecycle", "_runtime_plugin_assets",
    "_runtime_templates", "_runtime_watchdog", "_slug",
)
assert len(_SUBMODULES) == 24, f"expected 24 siblings, got {len(_SUBMODULES)}"

for _name in _SUBMODULES:
    try:
        _mod = __import__(f"openakita.orgs.{_name}", fromlist=["*"])
    except Exception:  # noqa: BLE001 -- defensive; never block import
        continue
    sys.modules[f"{__name__}.{_name}"] = _mod

del _name, _mod