"""Parity placeholder for ``OrgNodeScheduler`` (P9.3).

Activates as part of phase P9.3 when ``runtime/orgs/node_scheduler.py`` lands.
Target: 4 parametrised cases asserting v1 vs v2 parity
against recorded fixtures (see ``README.md`` for the template).
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="not yet implemented, P9.3 will activate", strict=True)
def test_node_scheduler_parity_placeholder() -> None:
    """Placeholder so the file exists in the gate baseline.

    P9.0 gate requires the xfail count under tests/parity/orgs/ to be
    exactly 6 (one per subsystem). The P9.3 landing replaces this
    placeholder with 4 parametrised cases.
    """
    raise NotImplementedError(
        "node_scheduler parity fixtures land in P9.3; this is the P9.0 skeleton"
    )
