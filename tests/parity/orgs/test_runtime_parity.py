"""Parity placeholder for ``OrgRuntime`` (P9.6).

Activates as part of phase P9.6 when ``runtime/orgs/runtime.py`` lands.
Target: 20 parametrised cases asserting v1 vs v2 parity
against recorded fixtures (see ``README.md`` for the template).
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="not yet implemented, P9.6 will activate", strict=True)
def test_runtime_parity_placeholder() -> None:
    """Placeholder so the file exists in the gate baseline.

    P9.0 gate requires the xfail count under tests/parity/orgs/ to be
    exactly 6 (one per subsystem). The P9.6 landing replaces this
    placeholder with 20 parametrised cases.
    """
    raise NotImplementedError(
        "runtime parity fixtures land in P9.6; this is the P9.0 skeleton"
    )
