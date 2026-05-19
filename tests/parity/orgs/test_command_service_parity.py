"""Parity placeholder for ``OrgCommandService`` (P9.4).

Activates as part of phase P9.4 when ``runtime/orgs/command_service.py`` lands.
Target: 10 parametrised cases asserting v1 vs v2 parity
against recorded fixtures (see ``README.md`` for the template).
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="not yet implemented, P9.4 will activate", strict=True)
def test_command_service_parity_placeholder() -> None:
    """Placeholder so the file exists in the gate baseline.

    P9.0 gate requires the xfail count under tests/parity/orgs/ to be
    exactly 6 (one per subsystem). The P9.4 landing replaces this
    placeholder with 10 parametrised cases.
    """
    raise NotImplementedError(
        "command_service parity fixtures land in P9.4; this is the P9.0 skeleton"
    )
