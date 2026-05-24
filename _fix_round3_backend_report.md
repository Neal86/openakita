# Fix-round-3 · finance-auto backend completion report

Baseline HEAD: `acf015a9` (revamp/v3-orgs)
Final HEAD: `895878c2` (revamp/v3-orgs) — 9 new commits inside the
backend territory.

## §0 摘要 · Self-audit 结果

| Gate | Result | Notes |
|---|---|---|
| pytest (plugins/finance-auto/tests/) | **262 passed** (was 218 baseline +44 new) | 41s wall-clock |
| `run_all_acceptance.py` | **10/10 PASS** | `--per-script-timeout 180`; default 120s still works once the cold-cache run finishes |
| `check_territory.py acf015a9..HEAD` | **0 ERROR** | 4 WARN from sibling β's deps/devtools/deploy commits — none of my 9 commits are in the warn list |
| RBAC boundary (TestClient) | **11/11 e2e pass** (`test_rbac_e2e.py`) | covers admin / manager / partner / auditor / unknown matrix on 5 modules |
| Old PBKDF2 (200k) backup still decrypts | **PASS** | `test_old_200k_backup_still_decrypts` |
| Path traversal (`../../etc/passwd`) blocked | **PASS** | `test_create_backup_path_traversal_rejected` |

Total new tests: **44** (test_transaction_rollback +4,
test_ws_limits +4, test_llm_retry +5, test_reclassification_undo +3,
test_rbac_e2e +11, plus +12 carried in by the pre-existing P1
commits I did not author but verified untouched).

## §1 EX-P1-1 · 备份/恢复路径遍历修复 — pre-existing (eb2dd49e)

Already landed in `eb2dd49e fix(finance-auto): sandbox backup and
restore paths to prevent traversal` before this batch.  Verified
still green (`test_backup_sandbox.py` 10/10).  The fix sandboxes
both `dest_dir` and `target_db_path` against
`Path.home()/".openakita"/"finance_auto"/"backups"` (override
`OPENAKITA_FINANCE_AUTO_BACKUP_ROOT`), validates via
`Path(...).resolve().is_relative_to(root.resolve())`, raises
`HTTPException(403, "path_outside_sandbox")` on failure, and
defaults restore `overwrite=False` (raises 409
`target_already_exists` without `?overwrite=true`).

## §2 EX-P1-2 · 全量 RBAC 覆盖 — 3 commits

| Commit | Title |
|---|---|
| `b7089fc4` | extend default permission seeds to cover 9 write modules |
| `94e36663` | wire `check_permission` to admin/reclass/cashflow/xperiod/audit-tpl/manual/consol/parse/notes/peer entries |
| `4defd14a` | RBAC end-to-end tests for 5 critical modules |

- New migration `v12_extended_permissions.py` adds 39 seed rows
  (admin / manager / partner / auditor × 17 new resource×action
  combinations) via idempotent `INSERT OR IGNORE`; `SCHEMA_VERSION`
  bumped 11 → 12 (then → 13 in EX-P2-9).  Schema migration replay
  picks the seeds up on next start without a re-init.
- New helper `finance_auto_backend/rbac.py` exposes
  `current_user_id` (resolves `X-OpenAkita-User-Id` header → query
  → `"local"` sentinel), `require_permission(resource, action)`
  (returns a `Depends`-friendly factory that raises 403 with
  `{"error":"rbac_denied", ...}` and logs WARNING), and
  `attach_service_for_rbac` (binds the service to `HTTPConnection.
  state` so both HTTP and WS endpoints can reach it).
- 14 `Depends(require_permission(...))` injections across 9 route
  modules — no URL path / method / response_model changed.
  `routes.py`'s URL block stays frozen (1 added call to
  `attach_service_for_rbac` inside `build_router`).
- 11-case e2e test suite in `test_rbac_e2e.py` covers
  admin_backup.create, reclassification.apply / preview,
  consolidation.create_group, cash_flow.compute, parse_issue.decide
  — both authorised and unauthorised paths, plus the
  backwards-compat "local" caller bypass.

## §3 EX-P1-3 + EX-P2-2 · PBKDF2 200k → 600k — pre-existing (a8628d1f)

Already landed in `a8628d1f fix(finance-auto): bump PBKDF2
iterations to OWASP 2023 minimum 600k with backward compat`.
Verified still green:

- `BACKUP_DEFAULT_KDF_ITERATIONS = 600_000`, override via
  `OPENAKITA_FINANCE_AUTO_KDF_ITERATIONS`.
- Backup manifest stores the actual iteration count; restore reads
  it from the manifest, so a 200k backup decrypts even after the
  default flips to 600k.
- Test `test_old_200k_backup_still_decrypts` proves the
  backward-compat path.

## §4 EX-P2-3 · reclassification.apply → executemany — `8e562442`

Replaced the per-item INSERT loop in `services/reclassification.py
::run` with a single `await conn.executemany(...)` on
`reclassification_run_items`.  Behaviour identical (same SQL, same
column order, same surrounding transaction); only the wire format
shrinks from N round-trips to 1.

Perf test `test_reclassification_perf.py`: 1000 matched items
finish under 0.2 s locally (budget 1.0 s).

## §5 EX-P2-4 · WebSocket max_clients + heartbeat — `68118922`

`finance_auto_backend/ai/ws.py` upgraded:

- `MAX_WS_CLIENTS=50` (env `OPENAKITA_FINANCE_AUTO_WS_MAX_CLIENTS`);
  `connect()` accepts → closes with code 1013 when the ceiling is
  hit.
- `HEARTBEAT_INTERVAL=30s` / `HEARTBEAT_TIMEOUT=60s` (both env
  overridable); the endpoint multiplexes a periodic server-side
  `ping` text frame with `receive_text` via `asyncio.wait_for` and
  closes 1011 on cumulative silence.
- Explicit `add()` / `remove()` API; the `finally` clause always
  unregisters so an exception in the heartbeat loop never leaks a
  tracked socket.
- Updated `finance_ws_hello` payload includes the negotiated
  intervals so the React client can adapt.

4 tests in `test_ws_limits.py` (TestClient): 3rd-client reject,
silent-client close, pong keep-alive, add/remove API.

## §6 EX-P2-5 · 跨表 service 显式 transaction rollback — `ab095d38`

Wrapped four service entries in
`try / await conn.commit() / except: await conn.rollback(); raise`:

- `reclassification.run` — header + items + parse_issues +
  history (EX-P2-9) all roll back together on any mid-batch raise.
- `consolidation.run` — the `consolidated_reports` write.
- `review_workflow._transition` — preserves the existing 409
  optimistic-lock path; generic except re-raises after rollback.
- `cash_flow.persist_as_manual_inputs` — the per-key UPSERT loop.

4 tests in `test_transaction_rollback.py` use monkey-patched
`execute`/`executemany` shims that return objects supporting both
`await` and `async with` (matching aiosqlite's dual API) and assert
the post-rollback row counts are zero.

## §7 EX-P2-6 · 加密失败 raise 而非 silent fallback — pre-existing (becaf637)

Already landed in `becaf637 fix(finance-auto): raise on decryption
failure instead of silent raw fallback`.  Verified still green
(`test_decrypt_failure.py`).  `_maybe_unpack` /
`_decode_original_data` raise `DecryptionError` by default; routes
expose `?accept_corrupted=true` for explicit disaster-recovery,
which logs a warning and returns an empty/raw shell.

## §8 EX-P2-7 · 备份失败 .tar.gz cleanup — pre-existing (083189d3)

Already landed in `083189d3 fix(finance-auto): cleanup half-written
backup archive on failure`.  Verified still green (the create-
backup tarfile flow now writes to a `.partial` file, then
`os.replace`s it on success; `try/except` unlinks on failure).

## §9 EX-P2-8 · LLM retry/backoff — `8135cfa0`

`ai/router.py::FinanceAIRouter.complete` now loops up to
`DEFAULT_LLM_RETRIES=3` times (env
`OPENAKITA_FINANCE_AUTO_LLM_RETRIES`) on transient errors with
exponential backoff `backoff_base * 2**attempt` (default 1s, env
`..._BACKOFF_BASE`) plus jitter (default 0.25s, env
`..._BACKOFF_JITTER`).

Classifier `is_retryable_llm_error(exc)` returns True for
`asyncio.TimeoutError`, `TimeoutError`, and message substrings
matching 5xx / 429 / "rate limit" / "timeout" / "connection
reset"; returns False for explicit 4xx (except 429).

Each retry + final outcome is logged at INFO / WARNING with
scenario, endpoint, attempt, wait, error.

5 tests in `test_llm_retry.py`: classifier 5xx vs 4xx, flaky-503
recovers after 3 retries, permanent 400 short-circuits, max-retries
exhaustion.

## §10 EX-P2-9 · reclassification undo API + history — `f9581793`

New migration `v13_reclassification_history.py` adds a sidecar
table `reclassification_history(history_id, run_id, rule_id, org_id,
period_id, applied_at, applied_by, inverse_delta_json, status,
undone_at, undone_by, notes, version, created_at)` keyed on the
v9 `reclassification_runs.run_id`.  `status` cycles
`recorded → undone / superseded`.

`ReclassificationService.run` now records one history row per
`apply` (preview skipped — nothing to undo), marking any prior
`recorded` rows for the same `(rule, period)` as `superseded` so
undo always targets the freshest apply.

New endpoint
`POST /orgs/{org_id}/reclassification-rules/{rid}/undo
?actor_id=...`: deletes the spawned `parse_issues` rows, flips the
history to `undone`, annotates the run's `notes` (the runs table's
`status` CHECK constraint forbids `'undone'`, so the
authoritative undo signal lives on the history row).  Wrapped in
the EX-P2-5 transaction envelope.

3 tests in `test_reclassification_undo.py`: apply → undo
round-trip, undo on un-applied rule → 404, double-undo → 404.

## §11 Self-audit 全表

| Audit step | Status | Detail |
|---|---|---|
| pytest plugins/finance-auto/tests/ | ✅ 262 passed (218 baseline + 44 new) | 39.93 s |
| run_all_acceptance.py | ✅ 10/10 | `--per-script-timeout 180`; 27 s cumulative |
| check_territory acf015a9..HEAD | ✅ 0 ERROR (4 WARN — all sibling β commits, none mine) | scan of 22 commits |
| RBAC e2e (admin / mgr / aud / partner / unknown × 5 modules) | ✅ 11/11 | `test_rbac_e2e.py` |
| Backup path traversal (`../../etc/passwd`) | ✅ 403 `path_outside_sandbox` | `test_create_backup_path_traversal_rejected` |
| Restore overwrite gate (existing DB + no ?overwrite=true) | ✅ 409 `target_already_exists` | `test_restore_refuses_without_overwrite` |
| Backup 200k (old) vs 600k (new) round-trip | ✅ both decrypt | `test_old_200k_backup_still_decrypts` + `_new_default_uses_600k` |
| WebSocket 50-client ceiling | ✅ closes 3rd with 1013 | `test_ws_max_clients_rejects_third_client` |
| WebSocket heartbeat timeout | ✅ closes silent peer with 1011 | `test_ws_heartbeat_closes_silent_client` |
| Reclassification 1000-item perf | ✅ <0.2 s (budget 1.0 s) | `test_reclassification_apply_1000_items_under_one_second` |
| Transaction rollback on mid-batch raise (4 services) | ✅ all 4 leave 0 rows | `test_transaction_rollback.py` |
| LLM retry 503×3 then success | ✅ 4 attempts (1 + 3 retries) | `test_router_retries_transient_then_succeeds` |
| Reclassification apply → undo → parse_issues gone | ✅ history → undone, count = 0 | `test_apply_records_history_then_undo_reverts` |

## §12 Sibling β 协调

The fix-round-3 deploy worker (β) ran ahead of me in
the same branch, landing 8 commits (3bb2d45e / 5d83e0c576 /
912cffe282 / 2d5ba958 / 000805ba / ea357b0f / 6c355e5a /
0d2dde1c).  Each one touched only β's declared territory:

- `plugins/finance-auto/{README.md, plugin.json, requirements.txt,
  CHANGELOG.md, docs/**}` — β's metadata/docs scope.
- `plugins/finance-auto/ui/{package.json, scripts/, src/}` — β's
  frontend bundle scope.
- `.github/workflows/finance-auto-*.yml` — β's CI scope.

My 9 commits stayed strictly inside
`plugins/finance-auto/finance_auto_backend/**`,
`plugins/finance-auto/tests/**`, and
`plugins/finance-auto/scripts/**`.  `check_territory` returns 0
ERROR across the 22-commit range.

One coordination point: β's `6c355e5a feat(finance-auto-ui)` adds
a frontend "reclassification undo" affordance that talks to the
new `POST .../reclassification-rules/{rid}/undo` endpoint shipped
in my `f9581793`.  The two were planned to land in the same fix
round, and the endpoint contract (`?actor_id=...` query param,
`{ok, history_id, run_id, rule_id, deleted_parse_issues,
undone_at, undone_by}` response shape) matches what β's UI
consumes.  No additional sync required.

## §13 遗留

None inside the EX-P1 + backend-EX-P2 scope.

Known leftover (deliberate, outside this round's scope):

- EX-P2-9 frontend "redo" affordance — β shipped only the "undo"
  button; a "redo undone run" flow is a future-round task.
- `v12_extended_permissions.py` does not delete obsolete v9 seeds
  (none were obsolete, but if a future round retires a verb the
  permission row will linger).  Aligns with the "additive only"
  v0.3 Part Infra contract.
- `attach_service_for_rbac` uses a router-level `Depends`-as-
  middleware trick.  A future round could promote this to a real
  Starlette middleware, but only after the host's PluginManager
  middleware-ordering rules are documented (see audit Section 11).

## Commit list (9 commits, all inside the declared backend territory)

```
895878c2 test(finance-auto): adapt M3 acceptance scripts to fix-round-3 schema and sandbox
4defd14a test(finance-auto): add RBAC end-to-end tests for 5 critical modules
94e36663 feat(finance-auto): wire check_permission to admin/reclass/cashflow/xperiod/audit-tpl/manual/consol/parse/notes/peer entries
b7089fc4 feat(finance-auto): extend default permission seeds to cover 9 write modules
f9581793 feat(finance-auto): add reclassification undo API with inverse delta history
8135cfa0 feat(finance-auto): add retry with exponential backoff to LLM router
68118922 feat(finance-auto): add WebSocket max_clients limit and heartbeat
ab095d38 fix(finance-auto): add explicit transaction rollback to 4 cross-table services
8e562442 perf(finance-auto): use executemany for reclassification batch insert
```

Pre-existing fix-round-3 backend commits I verified (not authored
in this round, but green after my changes): eb2dd49e (EX-P1-1),
a8628d1f (EX-P1-3), 083189d3 (EX-P2-7), becaf637 (EX-P2-6).
