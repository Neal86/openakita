"""Parity placeholder for ``OrgManager`` (P9.5).

Activates as part of phase P9.5 when ``runtime/orgs/manager.py`` lands.
Target: 12 parametrised cases asserting v1 vs v2 parity
against recorded fixtures (see ``README.md`` for the template).
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="not yet implemented, P9.5 will activate", strict=True)
def test_manager_parity_placeholder() -> None:
    """Placeholder so the file exists in the gate baseline.

    P9.0 gate requires the xfail count under tests/parity/orgs/ to be
    exactly 6 (one per subsystem). The P9.5 landing replaces this
    placeholder with 12 parametrised cases.
    """
    raise NotImplementedError(
        "manager parity fixtures land in P9.5; this is the P9.0 skeleton"
    )
