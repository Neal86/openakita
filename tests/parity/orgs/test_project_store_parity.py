"""Parity placeholder for ``OrgProjectStore`` (P9.2).

Activates as part of phase P9.2 when ``runtime/orgs/project_store.py`` lands.
Target: 6 parametrised cases asserting v1 vs v2 parity
against recorded fixtures (see ``README.md`` for the template).
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="not yet implemented, P9.2 will activate", strict=True)
def test_project_store_parity_placeholder() -> None:
    """Placeholder so the file exists in the gate baseline.

    P9.0 gate requires the xfail count under tests/parity/orgs/ to be
    exactly 6 (one per subsystem). The P9.2 landing replaces this
    placeholder with 6 parametrised cases.
    """
    raise NotImplementedError(
        "project_store parity fixtures land in P9.2; this is the P9.0 skeleton"
    )
