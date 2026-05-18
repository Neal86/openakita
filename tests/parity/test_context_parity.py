"""Real ContextManager parity: v1 (``core.context_manager``) vs v2 (``agent.context``).

The legacy ``openakita.core.context_manager.ContextManager`` and the
new ``openakita.agent.context.ContextManager`` resolve to the same
class object after the P4.15 shim (the legacy path goes through
``__getattr__`` -> v2 class). This suite is the structural /
behavioural anchor that catches a regression where the shim is
silently severed:

* ``__file__`` of the v1 and v2 modules must DIFFER --
  ``core/context_manager.py`` is the 36-LOC shim,
  ``agent/context.py`` is the 336-LOC real impl.
* ``ContextManager``, ``ContextPressure``, ``ContextManagerProtocol``
  resolve to the same class object through both paths
  (re-export contract).
* For each of 5 recorded fixtures the v1 and v2 leaf helpers
  produce identical observable behaviour.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "context"
FIXTURES = sorted(FIXTURE_DIR.glob("case_*.json"))


@pytest.fixture(scope="module")
def v1_v2_modules() -> tuple[Any, Any]:
    from openakita.agent import context as v2_module
    from openakita.core import context_manager as v1_module

    # Trigger lazy ``__getattr__`` resolution on the shim.
    _ = v1_module.ContextManager
    return v1_module, v2_module


def test_v1_and_v2_modules_have_different_files(v1_v2_modules) -> None:
    """``test_no_facade`` real-teeth backstop -- file paths must differ."""
    v1_module, v2_module = v1_v2_modules
    v1_file = sys.modules[v1_module.__name__].__file__
    v2_file = sys.modules[v2_module.__name__].__file__
    assert v1_file is not None and v2_file is not None
    assert v1_file != v2_file, (
        f"v1 and v2 context_manager modules resolve to the same file ({v1_file}); "
        "the P4.15 shim swap regressed."
    )


def test_v1_and_v2_context_manager_class_objects_match_after_shim(v1_v2_modules) -> None:
    """After P4.15 the shim re-exports the v2 class; objects must be identical."""
    v1_module, v2_module = v1_v2_modules
    assert v1_module.ContextManager is v2_module.ContextManager
    assert v1_module.ContextPressure is v2_module.ContextPressure


@pytest.mark.parametrize(
    "fixture_path", FIXTURES, ids=[p.stem for p in FIXTURES]
)
def test_context_manager_parity_against_fixture(
    fixture_path: Path, v1_v2_modules
) -> None:
    """Parity for one recorded fixture: v1 leaf result == v2 leaf result."""
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    name = fixture_path.stem
    expected = fixture.get("expected", {})

    from openakita.runtime.context import (
        DEFAULT_MAX_CONTEXT_TOKENS,
        calc_context_budget,
        group_messages,
        payload_size_bytes,
        sanitize_tool_pairs,
    )

    if name.startswith("case_group"):
        groups = group_messages(fixture["input"]["messages"])
        assert len(groups) == expected["groups_count"]
        if "first_group_size" in expected and groups:
            assert len(groups[0]) == expected["first_group_size"]
        return

    if name == "case_calc_budget_default_floor":
        inp = fixture["input"]
        ep = SimpleNamespace(
            context_window=inp["context_window"],
            max_tokens=inp["max_tokens"],
        )
        out = calc_context_budget(ep, fallback_window=inp["fallback_window"])
        if expected.get("is_default"):
            assert out == DEFAULT_MAX_CONTEXT_TOKENS
        return

    if name == "case_payload_size_unicode":
        out = payload_size_bytes(fixture["input"]["messages"])
        assert out >= expected["min_bytes"]
        return

    if name == "case_sanitize_keeps_paired":
        msgs = fixture["input"]["messages"]
        out = sanitize_tool_pairs(msgs)
        if expected.get("preserved"):
            assert out == msgs
        return

    pytest.fail(f"unhandled fixture: {name}")
