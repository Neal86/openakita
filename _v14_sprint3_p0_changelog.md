# Sprint-3 P0 Implementation Changelog (v14 audit response)

Status: implemented + reviewed (2 rounds), uncommitted at write time.
Baseline HEAD: `017e8259` (Sprint-2 P0 — DefaultAgentBuilder + status reconciliation).
Source: `_orgs_business_capability_audit_v3.md` §5.2 / §5.3 / §7.

## Scope

Two Sprint-3 P0 goals + the in-scope items of Pattern 1–5 sweep.

- P0-1 (D3 minimum dispatch): one entry node is **really** activated so the LLM no longer cosplays multiple roles single-handedly; `context.node_id` is no longer null; `delegation_logs/YYYYMMDD.jsonl` and `events.jsonl` get verifiable lines/events on every dispatch.
- P0-2 (D2 cancel propagation): a user cancel really cancels the inflight `asyncio.Task` running `Brain.messages_create_async`, so `CancelledError` propagates through `httpx` and stops token burn; `phase=cancelled` is reflected in status; `cancelled_roots` is populated.
- Pattern 1–5 sweep: Pattern 1 (placeholders) — `_NullAgentBuilder` already replaced in Sprint-2; remaining `_NullAgentBuilder` is the explicit fallback used when no real builder is registered (kept as TODO: real registry-driven swap is part of D4). Pattern 2 (HTTP/SSE accepted but no propagation) — `cancelled_roots:[]` fixed; `org stop` continues to be out-of-scope (next sprint F2). Patterns 3–5 reviewed — no new issues introduced; existing optional fields and trace-context plumbing are unchanged (set_trace_context overwrite is acknowledged but out-of-scope of this sprint).

## Modified files

```
M src/openakita/orgs/_runtime_agent_pipeline_executor.py   (+30)
M src/openakita/orgs/_runtime_dispatch.py                  (+97)
M src/openakita/orgs/command_service.py                    (+202 net)
M tests/parity/orgs/test_runtime_parity.py                 (cancelled_roots assertion)
M tests/runtime/orgs/test_command_status_reconciliation.py (agent_run_cancelled subscription)
M tests/runtime/orgs/test_runtime_contract.py              (cancelled_roots assertion)
A tests/runtime/orgs/test_cancel_propagates.py             (new, 6 tests)
A tests/runtime/orgs/test_entry_node_dispatch.py           (new, 7 tests)
```

Total source diff: 311 inserts / 18 deletes across 3 production modules — under the 500-line ADR threshold.

## P0-1: D3 entry-node dispatch — implementation summary

### What was wrong (v14 audit)

`command_service._schedule_run` was passing `request.target_node_id` (almost always `None` on root submit) directly to `runtime.send_command`. The runtime resolved a valid root node internally for the tracker, but the **executor pipeline** continued to see `None` and therefore propagated a null `node_id` into `set_trace_context` and the LLM debug payloads. Symptom: in v14 we measured `delegation_logs/today.jsonl` increment = 0 and `node_id == null` across 68 LLM debug files.

### Fix

- `command_service._schedule_run` (`src/openakita/orgs/command_service.py`)
  - Compute `effective_target = request.target_node_id or root_node_id` after resolving root from `_OrgManager`, then pass `effective_target` to `self._runtime.send_command(...)`.
  - Key decision: keep root resolution where it already lives (in `command_service`), do not duplicate node-pick logic into the dispatcher or executor; minimum-viable D3 is "the root resolved by the manager is the entry node".

- `_runtime_dispatch.send_command` (`src/openakita/orgs/_runtime_dispatch.py`)
  - After registering the tracker, emit `subtask_assigned` on the runtime event bus with `{org_id, command_id, parent_node, child_node, content_preview, ts}`.
  - Append the same payload to `data/delegation_logs/YYYYMMDD.jsonl` via `_append_delegation_log()`. Path resolution mirrors how the rest of `orgs/` derives `data/` from `Settings()`; if the directory cannot be created the write is silently skipped (production must not crash on a logging failure — same policy as `events.jsonl`).
  - Key decision: emit on a **separate** event name (`subtask_assigned`) so the existing `command_*` overlay logic in `command_service._handle_runtime_event` is untouched; we add receiver semantics later (Sprint-4 will turn this into a true `subtask_started` → `subtask_completed` lifecycle).

### Verifiable signals after this change

- `data/delegation_logs/YYYYMMDD.jsonl` will receive one JSONL line per dispatch (entry-node).
- `events.jsonl` will receive one `event_type=subtask_assigned` per dispatch.
- `data/llm_debug/llm_request_*.json` will carry a non-null `context.node_id` for the entry node's LLM call (because `_BrainBackedNodeAgent` already wires `set_trace_context(node_id=node_id, ...)` since Sprint-2 — the bug was purely that the value reaching it was `None`).

### Tests

`tests/runtime/orgs/test_entry_node_dispatch.py` (new):

- `test_run_minimal_forwards_resolved_root_when_target_is_none` — submits with `target_node_id=None`, asserts `runtime.send_command` received the manager-resolved root.
- `test_run_minimal_respects_explicit_target_node` — submits with explicit `target_node_id="other_node"`, asserts no override.
- `test_dispatch_emits_subtask_assigned_event` — uses an in-memory bus stub, asserts the new event payload shape.
- `test_dispatch_writes_delegation_log_jsonl_line` — uses a tmp_path-redirected `data/`, asserts the JSONL line.
- `test_send_command_org_missing_returns_error_without_log_write` — error-path defensive: no log on bad org_id.
- `test_cancel_user_command_populates_cancelled_roots` — see P0-2.
- `test_org_runtime_send_command_uses_real_target_node` — integration-style: runs through `OrgRuntime` instead of `_runtime_dispatch` directly.

## P0-2: D2 cancel propagation — implementation summary

### What was wrong (v14 audit)

Three layers had to be fixed for the cancel to be real:

1. `_runtime_dispatch.cancel_user_command` returned `cancelled_roots: []` even when a tracker existed — dispatcher knew which root was running but did not report it back.
2. `command_service` had no handle on the `asyncio.Task` running `_run_minimal`, so even a successful "cancel" request only marked the runtime tracker, not the task.
3. The executor and agent paths did not distinguish a `CancelledError` from a generic exception — they did not emit any event-bus signal, so the outcomes-overlay in `command_service` had no `event_ref="agent_run_cancelled"` to flip `phase=cancelled` on the public status.

### Fix

- `command_service.__init__` adds `self._inflight_tasks: dict[str, asyncio.Task[Any]] = {}`.
- `command_service._schedule_run` stores `task = loop.create_task(_run_minimal()); self._inflight_tasks[command_id] = task`.
- `command_service._run_minimal` wraps the body in `try/except asyncio.CancelledError`:
  - Sets the in-memory state to `status="cancelled", phase="cancelled", event_ref="agent_run_cancelled"`.
  - Persists this to the outcomes/state stores.
  - **Re-raises** `CancelledError` (mandatory: do not swallow — otherwise the running task ends up with `result=...` not `cancelled`).
- `command_service._run_minimal` `finally` clause does `self._inflight_tasks.pop(command_id, None)`.
- `command_service.cancel`:
  - First looks up `task = self._inflight_tasks.get(command_id)`; if present, `task.cancel()` (synchronous side effect — schedules `CancelledError` at the next await point inside the task).
  - Then delegates to `self._runtime.cancel_user_command(...)` so the runtime tracker / dispatch state stays consistent.
- `command_service.get_status` overlay: when `outcomes[cid].event_ref == "agent_run_cancelled"` and the in-memory `status` is still `"running"`, the public response is patched to `status="cancelled", phase="cancelled"`. This handles the fast-cancel race window where the outcome lands before the task object finishes unwinding.
- `command_service._update_command_state`: `"cancelled"` is added to the set of terminal statuses that imply a final `phase` (next to `"done"` and `"error"`).
- `command_service._purge_old_commands`: when purging, pop and `task.cancel()` any leftover inflight tasks. Defensive against restart races where stale tasks survive a soft restart of `CommandService`.
- `command_service._wire_event_bus`: subscribe to `agent_run_cancelled` in addition to the prior `agent_run_started`/`agent_run_succeeded`/`agent_run_failed`. Subscription is rebuilt around a `_make_event_handler(name)` closure so the explicit name reaches `_handle_agent_event(event, name)`; the old shape-based inference is kept as a backward-compatible fallback.
- `command_service._handle_agent_event`: accepts an optional `event_name`; sets `event_name = "agent_run_cancelled"` when called from the closure for that event, then writes `phase=cancelled, error={"code":"cancelled","message":"cancelled by user"}, event_ref="agent_run_cancelled"` to outcomes.
- `_runtime_dispatch.cancel_user_command`:
  - `cancelled_roots: [tracker.root_node_id]` is populated in both `already_done` and active-cancel branches; the dispatcher always knows which root was running.
- `_runtime_agent_pipeline_executor.activate_and_run`:
  - Wraps the inner `agent.run(task)` in `try/except asyncio.CancelledError`.
  - On `CancelledError`, emits `agent_run_cancelled` via the runtime bus (best-effort — a nested `CancelledError` from `emit` is swallowed so we always re-raise the original one).
  - Re-raises so the outer `_run_minimal` and the `asyncio.Task` complete with `cancelled` state.

### Why no `llm/client.py` change was needed

`Brain.messages_create_async` already calls `await self._client.create_with_retry(...)` which awaits an `httpx.AsyncClient` request. `httpx` propagates `asyncio.CancelledError` to its underlying stream — when our outer task is cancelled, `httpx` closes the TCP connection, the LLM provider stops streaming, and no further tokens are billed. We verified this by reading `core/_brain_legacy.py` and `llm/client.py` (no `except Exception:` swallowing `CancelledError`, no `asyncio.shield` around the request).

### Tests

`tests/runtime/orgs/test_cancel_propagates.py` (new):

- `test_cancel_actually_cancels_inflight_llm_task` — patches `Brain.messages_create_async` to `await asyncio.sleep(60)`. Submits → waits 0.2s → cancels → asserts: (a) the task is `done()` and `cancelled()` within 1s, (b) `get_status` returns `phase="cancelled"`, (c) the recorded outcome has `event_ref="agent_run_cancelled"`. Wraps the assert window with `TimeoutError` to fail loudly if cancel does not propagate.
- `test_cancel_records_inflight_task_on_submit` — asserts `command_id in service._inflight_tasks` right after submit and removed after natural completion.
- `test_cancel_on_unknown_command_returns_none` — defensive against ghost cancels.
- `test_cancel_already_done_skips_task_cancel` — task that already finished is not re-cancelled.
- `test_handle_agent_event_records_cancelled_outcome_with_named_event` — direct call to `_handle_agent_event(event, "agent_run_cancelled")` asserts the outcome shape.
- `test_get_status_overlay_flips_phase_when_cancel_outcome_lands_early` — fast-cancel race window.

Modified:

- `tests/runtime/orgs/test_command_status_reconciliation.py::test_service_subscribes_to_agent_run_events_when_bus_provided` — added `agent_run_cancelled` to the expected subscription set.
- `tests/runtime/orgs/test_runtime_contract.py::test_contract_cancel_user_command_running` — assertion now expects `cancelled_roots: ["n1"]`.
- `tests/parity/orgs/test_runtime_parity.py::test_parity_dispatch_cancel_user_command_running` — same shape update.

## Pattern 1–5 sweep results

| Pattern | Scope | Result |
|--------|------|--------|
| 1. Placeholders pretending to work | `src/openakita/orgs/_*.py`, `src/openakita/agents/`, `api/routes/orgs_v2_*` | `_NullAgentBuilder` is **intentional** as the fallback when no real builder is registered (DefaultAgentBuilder is now the default since Sprint-2). No further `class.*Stub` / `raise NotImplementedError` found in orgs/agents. `AggregatorBuilder` / `DispatcherBuilder` / `RouterBuilder` / `RetrieverBuilder` / `ProfileResolver` do not exist as separate classes today — they are encoded inside `_runtime_dispatch.py` + `_default_agent_builder.py` (left as D4 next-sprint work). |
| 2. HTTP/SSE accept-but-no-propagation | `routes/orgs_v2_*` | `cancelled_roots:[]` fixed as part of P0-2. `org_stop` still has the same `ok:true, paused:true` pattern but the underlying interrupt is F2 next-sprint scope; tracked as TODO in audit doc. No new offenders. |
| 3. Optional fields without default | `orgs/schemas*.py` | Re-grepped `Optional[OrgOutputScope]` / `Optional[CommandPhase]` / `Optional[NodeId]`; existing fields all carry defaults or explicit handling. No new fixes required. |
| 4. Duck-call `app.state.org_runtime.` | `api/routes/orgs_v2_*` | Re-grepped — only protocol-typed indirection remains (ADR-0011). No new duck-call regressions. |
| 5. Trace-context propagation (`set_trace_context`, `context.caller`, `context.node_id`) | `core/`, `orgs/`, `scheduler/`, `memory/`, `compiler_think/` | `_default_agent_builder._BrainBackedNodeAgent` already calls `set_trace_context(caller="orgs_v2.node_agent", node_id=node_id, ...)` since Sprint-2. The root cause of v14's null node_id was upstream (the value passed in) — fixed in P0-1. `set_trace_context` overwrites the prior context on every call; that race is acknowledged in v14 audit §6 and remains out of sprint scope. |

## Review notes

### Round 1 — code quality

- **Async correctness**: `CancelledError` is **always re-raised** in `_run_minimal`, `activate_and_run`, and `_BrainBackedNodeAgent.run`. Nested `try/except` around `bus.emit` only swallows secondary `Exception` (not `CancelledError`), so the original cancellation always wins.
- **None deref**: `_schedule_run` resolves `root_node_id` from manager before computing `effective_target`; if both `target_node_id` and resolved root are `None`, the existing error path (`error.invalid_org`) fires before dispatch. Tests cover both branches.
- **Concurrency**: `_inflight_tasks` is mutated only from `_schedule_run`, `_run_minimal.finally`, `cancel`, and `_purge_old_commands` — all on the same event loop. No locks needed.
- **Fast cancel race**: `get_status` overlay flips `phase=cancelled` as soon as the outcome lands (covered by `test_get_status_overlay_flips_phase_when_cancel_outcome_lands_early`). Without the overlay, a fast-cancel that returns to the HTTP caller before `_run_minimal` finished unwinding could surface `phase=running` for a brief window.
- **Restart safety**: `_purge_old_commands` cancels stale tasks. After process restart, `_inflight_tasks` is empty by definition; the persisted outcomes retain the last `phase` written, which is the correct behavior (no zombie `running` rows that we own).
- **Compatibility**: Existing Sprint-2 subscriptions (`agent_run_started`/`succeeded`/`failed`) keep their previous semantics; the new subscription is purely additive.

### Round 2 — CI / lint / packaging

- `pytest tests/runtime/orgs/ tests/api/ tests/parity/orgs/` — **679 passed, 3 xfailed, 2 failed (pre-existing)**.
  - The 2 failures (`tests/api/test_p97_beta_smoke.py::test_b19_create_node_schedule`, `tests/parity/orgs/test_frontend_stale_paths_sentinel.py::test_frontend_no_unauthorized_orgs_spec_paths`) are the same baseline failures present on `017e8259` — not introduced here.
  - 13 new tests added across `test_cancel_propagates.py` and `test_entry_node_dispatch.py`; all pass.
- `ruff check src/openakita/orgs/command_service.py src/openakita/orgs/_runtime_dispatch.py src/openakita/orgs/_runtime_agent_pipeline_executor.py` — clean. Full `ruff check src/` still surfaces 6 errors, all of which are unchanged from `017e8259` (in `core/_brain_legacy.py`, `core/errors.py`, `orgs/manager.py`) — not introduced by this sprint.
- `mypy src/openakita/orgs/command_service.py src/openakita/orgs/_runtime_dispatch.py src/openakita/orgs/_runtime_agent_pipeline_executor.py` — no new issues.
- CLI smoke: `python -c "from openakita.api import create_app; create_app()"` succeeds. No new dependencies in `pyproject.toml`.

## Out-of-scope (carried to next sprint)

- D3-extended: real chained subtask dispatch (`producer → screenwriter → art_director ...`), aggregator nodes, multi-hop delegation logs.
- D4: node-level tools / skills / MCP injection (nodes are still zero-tool — only the LLM text path is real).
- D5: artifacts / memory / departments persistence (still 0-file at the manager layer).
- F2: `org stop` real interruption during running (mirror of P0-2 at the org level — wider blast radius, deserves its own sprint).
- F4: watchdog for stuck long-running tasks.
- Trace-context overwrite race in `set_trace_context` (v14 audit §6).

## Next steps for the user

1. Restart backend (the source under `src/openakita/orgs/` is part of the running process, so the changes only land after restart).
2. Run v15 exploratory test against `aigc-video-studio` template:
   - Dispatch a complex task → verify `data/delegation_logs/<today>.jsonl` increments by ≥ 1 and `events.jsonl` carries a `subtask_assigned` event.
   - Open one `data/llm_debug/llm_request_*.json` for the entry node and verify `context.node_id` is **not null**.
   - Submit a long task → cancel after ~3 s → verify `phase=cancelled` (not `running`/`done`) and that the token delta is significantly lower than an uncancelled control.
3. If v15 still reports cosplay-style multi-role output, that is D3-extended (next-sprint scope) and is not regressed by this commit.
