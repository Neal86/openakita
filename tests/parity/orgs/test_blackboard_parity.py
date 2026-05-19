"""Parity placeholder for ``OrgBlackboard`` (P9.1).

Activates as part of phase P9.1 when ``runtime/orgs/blackboard.py`` lands.
Target: 8 parametrised cases asserting v1 vs v2 parity
against recorded fixtures (see ``README.md`` for the template).
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="not yet implemented, P9.1 will activate", strict=True)
def test_blackboard_parity_placeholder() -> None:
    """Placeholder so the file exists in the gate baseline.

    P9.0 gate requires the xfail count under tests/parity/orgs/ to be
    exactly 6 (one per subsystem). The P9.1 landing replaces this
    placeholder with 8 parametrised cases.
    """
    raise NotImplementedError(
        "blackboard parity fixtures land in P9.1; this is the P9.0 skeleton"
    )
