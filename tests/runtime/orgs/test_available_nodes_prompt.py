"""Sprint-5 unexpected-finding #1: closed node list in producer prompt.

Audit v5 §4.2 + §5.3: the v16 producer LLM invented a ``director``
node that did not exist in the spec. The dispatch parser tolerated it
(unknown_target -> skip) but the invention still cost one LLM round
and polluted the reply. Listing the real node ids in the system
prompt at depth 0 measurably reduces invention.

Pins:

* The block is emitted at depth 0.
* The block is NOT emitted for sub-agents (depth >= 1) so we do not
  encourage them to cosplay coordinator.
* The block renders both ``node_id`` and the role / label so the LLM
  picks the right target.
* An empty ``available_nodes`` tuple skips the block entirely
  (legacy / single-node org).
"""

from __future__ import annotations

from openakita.orgs._default_agent_builder import _persona_system_prompt
from openakita.orgs._runtime_agent_pipeline import AgentSpec


def _spec(**overrides: object) -> AgentSpec:
    defaults: dict[str, object] = {
        "org_id": "o1",
        "node_id": "producer",
        "role": "producer",
        "external_tools": (),
        "enable_file_tools": False,
    }
    defaults.update(overrides)
    return AgentSpec(**defaults)


def test_depth_zero_emits_available_nodes_block() -> None:
    """case id: p05.ennum.depth0_lists_nodes"""

    spec = _spec(
        available_nodes=(
            ("screenwriter", "screenwriter"),
            ("art-director", "art-director"),
            ("wb-hh-image", "image workbench"),
        )
    )
    prompt = _persona_system_prompt(spec, depth=0)
    assert "DIRECT reports" in prompt
    assert "screenwriter" in prompt
    assert "art-director" in prompt
    assert "wb-hh-image" in prompt
    assert "Do NOT invent new node ids" in prompt


def test_middle_node_with_reports_emits_block_at_depth_one() -> None:
    """case id: p05.ennum.mid_level_lists_reports

    ★ Multi-level routing: a MIDDLE node (depth >= 1) that itself has
    direct reports IS a sub-coordinator and MUST see its own dispatch
    menu so it can delegate DOWN (逐级下派). Pre-fix this was suppressed
    (only depth 0 got the menu), which flattened the org to two layers.
    """

    spec = _spec(
        node_id="planner",
        role="planner",
        available_nodes=(("writer-a", "writer A"), ("writer-b", "writer B")),
    )
    prompt = _persona_system_prompt(spec, depth=1)
    assert "DIRECT reports" in prompt
    assert "writer-a" in prompt
    assert "writer-b" in prompt
    # Mid-level framing, not the root-only "you own the whole request".
    assert "MIDDLE-LEVEL coordinator" in prompt


def test_leaf_node_gets_worker_instructions_not_dispatch() -> None:
    """case id: p05.ennum.leaf_no_menu

    A node with NO direct reports (empty ``available_nodes``) is a leaf:
    it must NOT see the dispatch menu and is told to do the work itself.
    """

    spec = _spec(
        node_id="writer-a",
        role="writer",
        available_nodes=(),
    )
    prompt = _persona_system_prompt(spec, depth=2)
    assert "DIRECT reports" not in prompt
    assert "leaf specialist" in prompt


def test_empty_available_nodes_skips_block() -> None:
    """case id: p05.ennum.no_nodes_no_block

    Legacy / single-node orgs leave ``available_nodes`` at its default
    empty tuple -> no dispatch menu (leaf-worker instruction instead).
    """

    prompt = _persona_system_prompt(_spec(), depth=0)
    assert "DIRECT reports" not in prompt


def test_nodes_without_labels_still_listed_by_id() -> None:
    """case id: p05.ennum.label_optional"""

    spec = _spec(available_nodes=(("x1", ""), ("x2", "")))
    prompt = _persona_system_prompt(spec, depth=0)
    assert "- x1" in prompt
    assert "- x2" in prompt


def test_subagent_depth_skips_block() -> None:
    """case id: p05.ennum.depth1_leaf_no_list

    A depth >= 1 node with NO reports is still a leaf and skips the menu
    (the multi-level enablement keys on having reports, not on depth).
    """

    spec = _spec(
        node_id="screenwriter",
        role="screenwriter",
        available_nodes=(),
    )
    prompt = _persona_system_prompt(spec, depth=1)
    assert "DIRECT reports" not in prompt
