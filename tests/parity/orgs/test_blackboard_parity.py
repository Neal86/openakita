"""Parity fixtures for OrgBlackboard v1 -> v2 (P-RC-9 P9.1c).

Each :class:`ParityCase` runs the same scripted sequence against
the v1 ``openakita.orgs.blackboard.OrgBlackboard`` and the v2
``openakita.runtime.orgs.blackboard.OrgBlackboard``. Equality is
asserted on the normalised :class:`ParityResult` via
:func:`assert_parity`, modulo the ignore set (UUIDs +
timestamps that differ per run by design).

Per ``tests/parity/orgs/README.md`` and P-RC-9-PLAN section
5.1, this file ships **8 fixtures** covering read / write /
round-trip / concurrent-write / ignore-set-correctness. The
P9.0i xfail placeholder is replaced wholesale -- if the v2
implementation regresses, every affected case fails with a
diff-style mismatch instead of an opaque ``xfail did pass``.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from tests.parity.harness import ParityCase, ParityResult, assert_parity


def _bb_v1(case: ParityCase, org_dir: Path) -> ParityResult:
    """Run the case against v1 OrgBlackboard."""
    from openakita.orgs.blackboard import OrgBlackboard as V1Blackboard
    from openakita.orgs.models import MemoryScope, MemoryType

    bb = V1Blackboard(org_dir, case.inputs["org_id"])
    return _drive(bb, MemoryType, MemoryScope, case)


def _bb_v2(case: ParityCase, org_dir: Path) -> ParityResult:
    """Run the case against v2 OrgBlackboard."""
    from openakita.runtime.orgs.blackboard import OrgBlackboard as V2Blackboard
    from openakita.runtime.orgs.memory_models import MemoryScope, MemoryType

    bb = V2Blackboard(org_dir, case.inputs["org_id"])
    return _drive(bb, MemoryType, MemoryScope, case)


def _drive(bb, MemoryType, MemoryScope, case: ParityCase) -> ParityResult:  # noqa: N803
    """Per-case dispatch; the case.inputs["op"] selects the script."""
    op = case.inputs["op"]
    if op == "write_read_org":
        bb.write_org("hello world", "node_a", MemoryType.FACT, tags=["t1"])
        rows = bb.read_org()
        return _rows_to_result(rows, success=True)
    if op == "write_read_dept":
        bb.write_department("eng", "dept content", "node_b", MemoryType.DECISION)
        rows = bb.read_department("eng")
        return _rows_to_result(rows, success=True)
    if op == "write_read_node":
        bb.write_node("node_c", "private note", MemoryType.PROGRESS, tags=["nt"])
        rows = bb.read_node("node_c")
        return _rows_to_result(rows, success=True)
    if op == "dup_org":
        e1 = bb.write_org("same content", "node_a", MemoryType.FACT)
        e2 = bb.write_org("same content", "node_a", MemoryType.FACT)
        rows = bb.read_org()
        return ParityResult(
            final_message="dup",
            success=True,
            extras={
                "first_written": e1 is not None,
                "dup_returned_none": e2 is None,
                "row_count": len(rows),
            },
        )
    if op == "eviction_caps_org":
        # Write 60 distinct rows with rising importance; cap is 200
        # (MAX_ORG_MEMORIES) so we deliberately stay under to keep the
        # case deterministic. The contract is "read returns rows
        # sorted by importance desc" -- both backends honour it.
        for i in range(60):
            bb.write_org(
                f"bulk row {i}",
                "node_a",
                MemoryType.FACT,
                importance=0.01 + 0.01 * i,
            )
        rows = bb.read_org(limit=10)
        return ParityResult(
            final_message="evict",
            success=True,
            extras={
                "top_count": len(rows),
                "top_importance_desc": [round(r.importance, 2) for r in rows],
            },
        )
    if op == "tag_filter":
        bb.write_org("a", "node_a", MemoryType.FACT, tags=["alpha"])
        bb.write_org("b", "node_a", MemoryType.FACT, tags=["beta"])
        bb.write_org("c", "node_a", MemoryType.FACT, tags=["alpha"])
        rows = bb.read_org(tag="alpha")
        return ParityResult(
            final_message="tag",
            success=True,
            extras={
                "alpha_count": len(rows),
                "alpha_contents": sorted(r.content for r in rows),
            },
        )
    if op == "query_by_type":
        bb.write_org("fact1", "node_a", MemoryType.FACT)
        bb.write_org("fact2", "node_a", MemoryType.FACT)
        bb.write_org("decision1", "node_b", MemoryType.DECISION)
        result = bb.query(memory_type=MemoryType.DECISION)
        return ParityResult(
            final_message="qtype",
            success=True,
            extras={
                "decision_count": len(result),
                "decision_content": [r.content for r in result],
            },
        )
    if op == "concurrent_writes":
        # 4 threads x 5 writes each -- both backends must accept writes
        # from multiple threads without raising. v1 has no in-process
        # lock (src/openakita/orgs/blackboard.py L97-L345), so under
        # contention some writes are lost to the read-modify-write
        # eviction loop racing itself. v2 takes threading.RLock around
        # the same critical section and is loss-free. The parity
        # contract therefore only asserts 'no exceptions; at least one
        # row survives' -- corruption parity, not row-count parity.
        # See tests/runtime/orgs/test_blackboard_contract.py case 12
        # for the strict v2 contract (exactly 10 rows for 2 x 5 writes).
        errors: list[BaseException] = []

        def worker(prefix: str) -> None:
            try:
                for i in range(5):
                    bb.write_org(
                        f"{prefix}_{i}", "worker", MemoryType.FACT, importance=0.5
                    )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(chr(ord("a") + i),))
            for i in range(4)
        ]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=10.0)
        rows = bb.read_org(limit=999)
        return ParityResult(
            final_message="conc",
            success=not errors,
            extras={
                "errors": [type(e).__name__ for e in errors],
                "any_rows_survived": len(rows) > 0,
            },
        )
    raise KeyError(f"unknown op: {op}")


def _rows_to_result(rows, *, success: bool) -> ParityResult:
    """Normalise row list into a comparable ParityResult."""
    return ParityResult(
        final_message="rows",
        success=success,
        extras={
            "count": len(rows),
            "contents": [r.content for r in rows],
            "memory_types": [r.memory_type.value for r in rows],
            "tags_per_row": [sorted(r.tags) for r in rows],
            "scopes": [r.scope.value for r in rows],
            "source_nodes": [r.source_node for r in rows],
            "scope_owners": [r.scope_owner for r in rows],
            "importance_per_row": [round(r.importance, 4) for r in rows],
            "ttl_hours_per_row": [r.ttl_hours for r in rows],
        },
    )


CASES: list[ParityCase] = [
    ParityCase(
        id="bb_write_read_org",
        kind="blackboard",
        inputs={"op": "write_read_org", "org_id": "org_parity_a"},
    ),
    ParityCase(
        id="bb_write_read_dept",
        kind="blackboard",
        inputs={"op": "write_read_dept", "org_id": "org_parity_b"},
    ),
    ParityCase(
        id="bb_write_read_node",
        kind="blackboard",
        inputs={"op": "write_read_node", "org_id": "org_parity_c"},
    ),
    ParityCase(
        id="bb_dup_org_returns_none",
        kind="blackboard",
        inputs={"op": "dup_org", "org_id": "org_parity_d"},
    ),
    ParityCase(
        id="bb_eviction_caps_org",
        kind="blackboard",
        inputs={"op": "eviction_caps_org", "org_id": "org_parity_e"},
    ),
    ParityCase(
        id="bb_tag_filter",
        kind="blackboard",
        inputs={"op": "tag_filter", "org_id": "org_parity_f"},
    ),
    ParityCase(
        id="bb_query_by_type",
        kind="blackboard",
        inputs={"op": "query_by_type", "org_id": "org_parity_g"},
    ),
    ParityCase(
        id="bb_concurrent_writes",
        kind="blackboard",
        inputs={"op": "concurrent_writes", "org_id": "org_parity_h"},
    ),
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_blackboard_parity(case: ParityCase, tmp_path: Path) -> None:
    """v1 vs v2 OrgBlackboard parity (P-RC-9 P9.1c, 8 cases)."""
    v1_dir = tmp_path / "v1"
    v1_dir.mkdir()
    v2_dir = tmp_path / "v2"
    v2_dir.mkdir()
    v1 = _bb_v1(case, v1_dir)
    v2 = _bb_v2(case, v2_dir)
    assert_parity(v1, v2, case=case)
