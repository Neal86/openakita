"""Real ToolExecutor parity: v1 (``core.tool_executor``) vs v2 (``agent.tools``).

The legacy ``openakita.core.tool_executor.ToolExecutor`` and the new
``openakita.agent.tools.ToolExecutor`` resolve to the same class
object after the P4.11 shim (the legacy path goes through
``__getattr__`` -> v2 class). This suite is the structural /
behavioural anchor that catches a regression where the shim is
silently severed (e.g. someone restores the legacy giant under
``core.tool_executor``):

* ``__file__`` of the v1 and v2 modules must DIFFER --
  ``core/tool_executor.py`` is the 41-LOC shim,
  ``agent/tools.py`` is the 347-LOC real impl.
* ``ToolExecutor``, ``ToolSkipped``, ``smart_truncate``,
  ``save_overflow`` resolve to the same object through both paths
  (re-export contract).
* For each of 5 recorded fixtures the v1 and v2 helpers produce
  identical observable behaviour (truncate text, save sidecar,
  classify retry).

The fixtures live under ``tests/parity/fixtures/tools/`` so adding
a regression case is a one-file edit + free re-run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tools"
FIXTURES = sorted(FIXTURE_DIR.glob("case_*.json"))


@pytest.fixture(scope="module")
def v1_v2_modules() -> tuple[Any, Any]:
    from openakita.agent import tools as v2_module
    from openakita.core import tool_executor as v1_module

    # Trigger the lazy ``__getattr__`` resolution on the shim.
    _ = v1_module.ToolExecutor
    return v1_module, v2_module


def test_v1_and_v2_modules_have_different_files(v1_v2_modules) -> None:
    """``test_no_facade`` real-teeth backstop -- file paths must differ."""
    v1_module, v2_module = v1_v2_modules
    v1_file = sys.modules[v1_module.__name__].__file__
    v2_file = sys.modules[v2_module.__name__].__file__
    assert v1_file is not None and v2_file is not None
    assert v1_file != v2_file, (
        f"v1 and v2 tool_executor modules resolve to the same file ({v1_file}); "
        "the P4.11 shim swap regressed."
    )


def test_v1_and_v2_tool_executor_class_objects_match_after_shim(v1_v2_modules) -> None:
    """After P4.11 the shim re-exports the v2 class; objects must be identical."""
    v1_module, v2_module = v1_v2_modules
    assert v1_module.ToolExecutor is v2_module.ToolExecutor
    assert v1_module.ToolSkipped is v2_module.ToolSkipped
    assert v1_module.smart_truncate is v2_module.smart_truncate
    assert v1_module.save_overflow is v2_module.save_overflow


@pytest.mark.parametrize(
    "fixture_path", FIXTURES, ids=[p.stem for p in FIXTURES]
)
def test_tool_executor_parity_against_fixture(
    fixture_path: Path, v1_v2_modules, tmp_path: Path
) -> None:
    """Parity for one recorded fixture: v1 helper result == v2 helper result."""
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    v1_module, v2_module = v1_v2_modules
    name = fixture_path.stem
    expected = fixture.get("expected", {})

    if name.startswith("case_truncate"):
        inp = fixture["input"]
        kwargs = {k: v for k, v in inp.items() if k not in ("content", "limit")}
        out_v1, was_v1 = v1_module.smart_truncate(
            inp["content"], inp["limit"], **kwargs
        )
        out_v2, was_v2 = v2_module.smart_truncate(
            inp["content"], inp["limit"], **kwargs
        )
        assert out_v1 == out_v2 and was_v1 == was_v2
        if "out" in expected:
            assert out_v2 == expected["out"]
        if "was_truncated" in expected:
            assert was_v2 == expected["was_truncated"]
        if "starts_with" in expected:
            assert out_v2.startswith(expected["starts_with"])
        if "ends_with" in expected:
            assert out_v2.endswith(expected["ends_with"])
        if "contains" in expected:
            assert expected["contains"] in out_v2
        return

    if name == "case_overflow_save_and_read":
        inp = fixture["input"]
        path_v1 = v1_module.save_overflow(
            inp["tool_name"], inp["content"], directory=tmp_path, max_files=10
        )
        path_v2 = v2_module.save_overflow(
            inp["tool_name"], inp["content"], directory=tmp_path, max_files=10
        )
        assert Path(path_v1).exists()
        assert Path(path_v2).exists()
        assert Path(path_v1).read_text(encoding="utf-8") == expected["content"]
        assert Path(path_v2).read_text(encoding="utf-8") == expected["content"]
        return

    if name == "case_retry_predicate":
        # Both paths must agree that ToolSkipped is non-retriable.
        skipped = v1_module.ToolSkipped("user declined")
        from openakita.runtime.retry_policy import is_retriable_tool_error
        assert is_retriable_tool_error(skipped) is expected["retriable"]
        return

    pytest.fail(f"unhandled fixture: {name}")
