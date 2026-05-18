"""Re-export shim — :class:`UserCancelledError` moved to ``agent.errors``.

The canonical home of :class:`UserCancelledError` is now
:mod:`openakita.agent.errors`, per ADR-0003 and the Phase 2 sub-commit
plan in ``docs/revamp/core_audit.md``. This shim keeps every existing
import path working — including the lazy attribute exposure in
``openakita/core/__init__.py`` — until Phase 8 mechanically removes
the legacy ``core/`` package.

Do not add new code here.
"""

from __future__ import annotations

from openakita.agent.errors import UserCancelledError

__all__ = ["UserCancelledError"]
