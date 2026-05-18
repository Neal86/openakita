# OpenAkita Backend Revamp — Status

This document is the authoritative ledger of what the v2 fork-style
rewrite has shipped, what is in flight, and what every next session
should pick up. It complements the plan file
(`openakita_full_backend_revamp_e6d8610d.plan.md`) and the ADRs under
`docs/adr/`.

Branch: `revamp/v2` (forked from `main`).
ADR sign-off gate: **G0 pending — every ADR is `Status: Proposed`.**
A user-led ADR review is the gate to flip them all to `Accepted`.

## Scoreboard

| Phase | Status | Code commits on `revamp/v2` | Tests passing |
|---|---|---|---|
| 0 — ADRs (10 docs) | **Complete** | 10 | n/a |
| 1 — Foundation (runtime/ leaf modules) | **Complete** | 8 | 99 runtime tests |
| 2 — Agent rewrite | **In progress (foundation slice)** | 1 (`agent/state.py`) | 17 agent tests |
| 3 — Runtime engine (supervisor + messenger + guardrail) | **In progress (critical path complete)** | 5 (`ledger`, `stall_detector`, `supervisor`, `messenger`, `guardrail/`) | 82 new runtime tests |
| 4 — Nodes | Pending | 0 | — |
| 5 — Templates | Pending | 0 | — |
| 6 — API / channels swap | Pending | 0 | — |
| 7 — Cutover + data migration | Pending | 0 | — |
| 8 — Legacy removal | Pending | 0 | — |

Total to date: **24 code commits + 10 ADR commits = 34 commits on
`revamp/v2`**, all lint-clean (ruff), test-green (198 / 198 in
`tests/runtime/` + `tests/agent/`).

## What v2 already delivers

The dual-ledger orchestration that ADR-0004 promises is end-to-end
working at module level:

```
TaskLedger (outer)               StallDetector
        │                                │
        ▼                                ▼
 Supervisor.run() ─── per turn ──► ProgressLedger ──► verdict ──► (DONE | PROCEED |
        │                                                          SUSPECT | REPLAN |
        │                                                          OUT_OF_TURNS)
        ├── stream events:    progress_ledger / checkpoints / lifecycle / tasks / updates
        ├── checkpoints:      after every turn, on accepted deliverable, on cancel
        ├── cancel:           cooperative via CancellationToken, writes a final ckpt
        └── delegate:         Messenger.deliver(speaker, instruction, ...) ──► node
                                                                        │
                                                                        ▼
                                                              GuardrailRunner.evaluate()
                                                              (OK | RETRY | HARD_FAIL)
```

The duplicate-storyboard regression (the headline pain in the user's
original report) cannot reproduce in v2 because:

1. wall-clock cancels are no longer in the loop (`max_task_seconds`
   has no v2 equivalent in the supervisor's decision path);
2. when a long step is *progressing*, the LLM says
   `is_progress_being_made=true` and the stall counter regenerates;
3. when a step actually stalls, the supervisor *replans* with new
   facts and a new plan — it does not cancel and re-delegate the same
   sub-task to the same node;
4. cancellations save a final checkpoint so resume is exact.

`tests/runtime/test_stall_detector.py::test_regression_long_progressing_storyboard_does_not_replan`
encodes the regression test for this.

## File map (so far)

```
docs/adr/
  README.md
  0001-fork-style-rewrite.md          ADR-0001 (signed off at G0)
  0002-runtime-architecture.md
  0003-agent-architecture.md
  0004-dual-ledger-supervisor.md
  0005-checkpoint-contract.md
  0006-stream-channels-schema.md
  0007-node-protocol-and-types.md
  0008-template-registry.md
  0009-plugin-workbench-manifest.md
  0010-data-migration.md

docs/revamp/
  STATUS.md                            (this file)

src/openakita/runtime/
  __init__.py                          public model exports
  models.py                            OrgV2, NodeV2, EdgeV2, …
  cancel_token.py                      CancellationToken / CancelledByToken
  retry_policy.py                      RetryPolicy + retriable taxonomy
  stream.py                            StreamBus + 8 channels
  event_store.py                       hash-chained SQLite WAL log
  checkpoint.py                        BaseCheckpointer + MemoryCheckpointer
  backends/
    __init__.py
    sqlite.py                          SqliteCheckpointer
    json_file.py                       JsonFileCheckpointer
  ledger.py                            TaskLedger + ProgressLedger + parser
  stall_detector.py                    n_stalls regen logic
  supervisor.py                        outer/inner loop end-to-end
  messenger.py                         address resolution + cancel-aware deliver
  guardrail/
    __init__.py
    runner.py                          GuardrailRunner + verdict aggregation
    builtin.py                         min/max length, required fields, regex

src/openakita/agent/
  __init__.py                          empty shell (Phase 2 fills it)
  state.py                             v2 minimal TaskState + AgentState

tests/runtime/                         99 tests (Phase 1) + 82 tests (Phase 3) = 181
tests/agent/                           17 tests
```

## What is *not* shipped yet (continuation map)

Each entry below names the module, its ADR, the legacy file it
replaces (with line count), and the rough effort.

### Phase 2 — Agent core, remaining slices

The agent's leaf modules above the Phase-1 foundation. Each is one
focused commit with tests.

| Module | ADR | Replaces | Legacy lines | Cap (lines) |
|---|---|---|---|---|
| `agent/identity.py` | ADR-0003 | `core/identity.py` | 495 | 250 |
| `agent/permission.py` | ADR-0003 | `core/permission.py` | 455 | 250 |
| `agent/audit.py` | ADR-0003 | `core/audit_logger.py` | 177 | 150 |
| `agent/output_guard.py` | ADR-0003 | `core/agent_output_guard.py` | 86 | 200 |
| `agent/prompt.py` | ADR-0003 | `core/prompt_assembler.py` | 157 | 200 |
| `agent/context.py` | ADR-0003 | `core/context_manager.py` | 1 569 | 400 |
| `agent/tools.py` | ADR-0003 | `core/tool_executor.py` | 1 609 | 300 |
| `agent/brain.py` | ADR-0003 | `core/brain.py` | 1 698 | 400 |
| **`agent/reasoning.py`** | ADR-0003 | `core/reasoning_engine.py` | **7 987** | **600** |
| **`agent/core.py`** | ADR-0003 | `core/agent.py` | **8 433** | **500** |
| `agent/facade.py` | ADR-0003 | n/a | 0 | 100 |

The two big ones (`reasoning.py` and `core.py`) need a parity harness
under `tests/parity/` that runs identical inputs through the legacy
and the v2 paths. The plan reserves Phase 2 (W6-10) for this; expect
the v2 reasoning loop to be implemented as a state graph driven by
`runtime/state_graph.py` (still pending — see Phase 3 below) so the
full loop body fits in `reasoning.py`.

### Phase 3 — Runtime engine, remaining slices

| Module | ADR | Notes |
|---|---|---|
| `runtime/state_graph.py` | ADR-0007 | LangGraph-style BSP engine. Required for ConditionNode + multi-node fan-out. The supervisor + messenger work end-to-end without it for single-flight, hierarchical orgs (the AIGC studio shape today). |

### Phase 4 — Nodes

| Module | ADR | Notes |
|---|---|---|
| `runtime/nodes/base.py` | ADR-0007 | NodeProtocol + NodeContext |
| `runtime/nodes/llm_node.py` | ADR-0007 | Default node hosting `agent.Agent`. Depends on Phase 2's `agent.facade.Agent`. |
| `runtime/nodes/workbench_node.py` | ADR-0007, ADR-0009 | First-class plugin host. Reads WORKBENCH manifest. |
| `runtime/nodes/tool_node.py` | ADR-0007 | Deterministic single-tool step. |
| `runtime/nodes/condition_node.py` | ADR-0007 | LLM/rule branch. Needs `state_graph`. |
| `runtime/nodes/human_review_node.py` | ADR-0007 | `interrupt_before` semantics. |

The first plugin to adopt `WORKBENCH` is `happyhorse-video`, because
its capability surface (`t2i`, `i2v`, `s2v`, `photo_speak`,
`storyboard`) matches every WorkbenchNode test scenario.

### Phase 5 — Templates

`runtime/templates/registry.py`, `runtime/templates/schema.py`, and
one file per built-in template under `runtime/templates/builtin/`,
starting with `aigc_video_studio.py`. The legacy
`orgs/templates.py` (1 234 lines) and
`orgs/plugin_workbench_templates.py` (225 lines) are deleted in
Phase 8.

### Phase 6 — API / channels swap

* `src/openakita/api/routes/orgs_v2.py` mounts the v2 facade behind
  `runtime_v2_enabled`;
* `src/openakita/channels/gateway.py` learns to route per-org based
  on the same flag;
* `apps/setup-center/src/components/OrgChatPanel.tsx` subscribes to
  the multi-channel StreamBus and renders the progress-ledger
  timeline.

### Phase 7 — Cutover

`scripts/migrate_orgs_to_legacy.py` (ADR-0010) plus
`runtime.facade.bootstrap_builtins()` for the fresh-start data
policy. 7-day burn-in is not gated by code; it is a runbook step.

### Phase 8 — Legacy removal

Mechanical `git rm` of `src/openakita/orgs/` and the rewritten
`src/openakita/core/*.py` files. One commit per concern so a `git
log` reader can diff the world before / after.

## How to resume in the next session

1. Read this `STATUS.md` first.
2. If continuing Phase 2: pick the smallest unfinished module from
   the list above and stand it up under `src/openakita/agent/` with
   a test file under `tests/agent/`.
3. If continuing Phase 4 (nodes): start with `nodes/base.py` because
   every other node imports from it. Then implement `LLMNode`
   thinly using whatever Phase 2 surface exists at that point —
   even a stub `Agent` is enough to integrate.
4. Always:
   * one logical change per commit, English commit body, mention
     the relevant ADR;
   * `python -m pytest tests/runtime tests/agent --no-header -q`
     before every commit;
   * `python -m ruff check src/openakita/runtime src/openakita/agent
     tests/runtime tests/agent` before every commit.
5. Never edit the plan file or the ADR `Status:` lines without a
   user-led review.

## How to *use* what already exists today

Even before Phases 4-7 land, the v2 supervisor stack is usable for
small experiments:

```python
import asyncio
from openakita.runtime.checkpoint import MemoryCheckpointer
from openakita.runtime.stream import StreamBus
from openakita.runtime.supervisor import Supervisor, DelegationResult
from openakita.runtime.messenger import Messenger, InMemoryNodeRegistry

# 1. Define a fake brain that satisfies SupervisorBrain.
# 2. Register a node on an InMemoryNodeRegistry.
# 3. messenger.bind_for_command(...) gives you the deliver callable.
# 4. Pass everything into Supervisor and call await sup.run().
```

The integration test in `tests/runtime/test_supervisor.py` is the
canonical wiring example; copy it as a starting point.
