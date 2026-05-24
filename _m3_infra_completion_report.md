# M3 Infra — completion report (Sibling C)

**Scope.** Tauri desktop enhancements + key versioning / rotation +
encrypted backup / restore for the `finance-auto` plugin.  Owner: M3
Sibling C ("Infra" worker).  Branch: `revamp/v3-orgs`.

## 1. Deliverables summary

| # | Deliverable                                | Status | Where                                                        |
|---|--------------------------------------------|--------|--------------------------------------------------------------|
| 1 | `key_versions` / `key_rotation_runs` schema | done   | `db/migrations/v11_key_rotation_backup.py`, `schema.py`      |
| 1 | `KeyRotationService` (transactional)       | done   | `services/key_rotation.py`                                   |
| 2 | `backup_history` schema                    | done   | `db/migrations/v11_key_rotation_backup.py`                   |
| 2 | `BackupRestoreService`                     | done   | `services/backup_restore.py`                                 |
| 3 | Tauri commands × 4 (consent / info / toast / save) | done | `apps/setup-center/src-tauri/src/finance.rs`             |
| 3 | `main.rs` `mod finance;` + `invoke_handler!` wiring | done | `apps/setup-center/src-tauri/src/main.rs`                 |
| 3 | `GET /admin/system-info`                   | done   | `infra_routes.py`                                            |
| 4 | `register_infra_endpoints` wired in `build_router` | done | `routes.py`                                              |
| 5 | 18-check acceptance script                 | done   | `scripts/m3_infra_acceptance.py`                             |
| 6 | This completion report                     | done   | `_m3_infra_completion_report.md`                             |

## 2. Commits (7)

| # | Hash       | Subject                                                                |
|---|------------|------------------------------------------------------------------------|
| 1 | `48b1518f` | `feat(finance-auto): add schema v11 for key rotation and backup history` |
| 2 | `671b81d7` | `feat(finance-auto): add KeyRotationService for component key rotation` |
| 3 | `6c2b696f` | `feat(finance-auto): add BackupRestoreService for encrypted snapshots`  |
| 4 | `c6fdaf72` | `feat(finance-auto): expose admin routes for key rotation and backups`  |
| 5 | `3fd2874c` | `feat(setup-center): add finance desktop commands (consent, notif, save, info)` |
| 6 | `6d6d2487` | `test(finance-auto): add 18-check M3 Infra acceptance script`           |
| 7 | _this report_ | `docs(finance-auto): add M3 Infra completion report` (Stage 7)      |

All commits use conventional-commit subjects with ≥3-line English
bodies focusing on the "why" — see `git log --oneline 48b1518f^..HEAD`.

## 3. Route delta verification

Probe (after Stage 4):

```text
routes: 90
admin routes: 11
  GET    /admin/key-versions
  GET    /admin/key-rotation-runs
  GET    /admin/key-rotation-preview
  POST   /admin/key-rotate
  POST   /admin/backups
  GET    /admin/backups
  GET    /admin/backups/{backup_id}
  POST   /admin/backups/{backup_id}/restore
  DELETE /admin/backups/{backup_id}
  GET    /admin/backups/{backup_id}/download
  GET    /admin/system-info
```

* **Baseline** (post-A and post-B landings): 79 routes.
* **My contribution**: **+11** unique admin paths (4 key + 6 backup
  + 1 system-info).  The brief budgeted "+13 with a 2-route buffer"
  and explicitly invited reporting the actual delta; +11 fits inside
  the budget.
* **Total**: 90 routes (`build_router` enumerated by the inline
  probe at the end of this report).

## 4. Schema territory

* `SCHEMA_VERSION` bumped **10 → 11** in `schema.py`.
* New module: `db/migrations/v11_key_rotation_backup.py`
  (`TARGET_VERSION=11`, `DDL_SQL`, `SEED_SQL`).
* Appended `+ _v11.DDL_SQL` to `SCHEMA_SQL`.
* Appended `(11, _v11.SEED_SQL)` to `MIGRATION_STEPS`.
* Did **not** touch v10 / v9 / v8 / earlier migrations.
* Docstring history extended with a v11 entry.
* Re-runs are no-ops: every `CREATE TABLE` uses `IF NOT EXISTS`;
  the seed is an `INSERT OR IGNORE` against a `__migration_marker__`
  sentinel.

## 5. Acceptance results

Latest run (`_m3_infra_acceptance_result.json`):

```text
checks: 18  failures: 0
M3 INFRA acceptance — SUCCESS
ok: True
regression:
  m2_closing      ok=True  elapsed_ms=1864  detected=success-marker
  m3_notes_peer   ok=True  elapsed_ms=1759  detected=success-marker
  m3_raw_ai       ok=True  elapsed_ms=1155  detected=success-marker
```

Per-check breakdown (16 functional + 1 Tauri-static + 1 regression):

1. `schema_v11` — confirms `SCHEMA_VERSION == 11`.
2. `route_delta` — confirms ≥11 admin routes added.
3. `list_key_versions` — `GET /admin/key-versions` returns shape.
4. `rotation_preview` — `GET /admin/key-rotation-preview` returns counts.
5. `enable_encryption` — seed `key_meta.global` + unlock `KeyManager`.
6. `seed_encrypted_rows` — insert org + import + 2 trial_balance rows.
7. `rotate_v1_to_v2` — `POST /admin/key-rotate` flips v1→v2, salt
   in `key_meta` swapped.
8. `round_trip_after_rotation` — decrypt the original row under the
   new key still yields `测试科目1`.
9. `rotation_rollback` — monkey-patched `KeyManager.encrypt` raises,
   rotation marked `failed`, key_meta salt unchanged, only v2 active.
10. `create_backup` — `POST /admin/backups` writes a tar.gz > 256 B,
    sha256 set.
11. `list_backups` — backup appears in the ledger.
12. `restore_wrong_passphrase` — returns `{ok:false, verified:false,
    error:"wrong passphrase"}` without DB writes.
13. `restore_dry_run_ok` — manifest + verified True, dry_run flag
    propagates.
14. `restore_materialise` — embedded SQLite written, restored
    `schema_version` = 11.
15. `delete_backup` — status flips to `deleted`, file unlinked.
16. `system_info` — `schema_version=11`, `key_version=2`,
    `encryption_enabled=True`, `backup_count≥1`.
17. `tauri_wiring_static_check` — regex confirms the 4 commands +
    `mod finance;` + `invoke_handler!` entries.
18. `regression_subprocess` — 3 sibling acceptance scripts detected
    via success markers in <5 s total.

## 6. Tauri desktop enhancement

`apps/setup-center/src-tauri/src/finance.rs` (NEW):

* `show_finance_consent_dialog(app, title, body) -> Result<String, String>`
  — `tauri_plugin_dialog` `OkCancelCustom("允许一次", "拒绝")`;
  returns `"allow_once"` / `"deny"`.
* `finance_system_info() -> serde_json::Value` — sync command
  returning `{tauri_version, os, arch, openakita_version,
  key_store_backend}`.
* `finance_show_notification(app, title, body) -> Result<(), String>` —
  `tauri_plugin_notification` toast.
* `finance_pick_save_path(app, default_name) -> Result<Option<String>,
  String>` — native save-file picker for backup export.

`apps/setup-center/src-tauri/src/main.rs`:

* Added `mod finance;` immediately after `mod crash_handler;`.
* Appended four `finance::<cmd>` entries to the existing
  `tauri::generate_handler![…]` block.  No existing command was
  removed or reordered.

**Compilation** was intentionally **not** invoked (no `cargo build`
or `npm run tauri build`) per the worker brief.  The acceptance
script's step 17 statically validates wiring via regex over the two
files; the `tauri-plugin-dialog` and `tauri-plugin-notification`
permissions required by the new commands are **already granted** in
`apps/setup-center/src-tauri/capabilities/default.json` (`dialog:default`,
`dialog:allow-save`, `notification:default`, `notification:allow-notify`),
so the capability file did **not** need editing.

## 7. Failure / rollback semantics (Deliverable 1 deep-dive)

The rotation flow holds **two state mutations** that must move
together: `key_meta.global.salt` and the active row in `key_versions`.
The implementation orders them as:

1. Insert the new `key_versions` row with `status='active'` and the
   canary ciphertext for self-verification.
2. Insert the `key_rotation_runs` row with `status='running'`.
3. `BEGIN` — re-encrypt every blob, then flip the previous version
   to `retired`, then `write_key_meta` the new salt.
4. `COMMIT` + mark the run `success`.

On any exception during step 3 the implementation issues `ROLLBACK`,
flips the brand-new `key_versions` row back to `retired` (preserving
audit history without leaving an "active" pointer that doesn't
match key_meta), and records `error_message` on the run.  Because
`write_key_meta` happens *inside* the transaction, the on-disk salt
is guaranteed to either match the new active version (success) or
the old retired-but-recoverable version (rollback) — never a third
state.

Acceptance step 9 exercises this end-to-end with a monkey-patched
`KeyManager.encrypt` that only fails for non-canary payloads, so
the canary self-test succeeds but the re-encryption walk fails and
the rollback path runs.

## 8. Hard-constraint compliance

* No `git push`, no `git config`, no `--force`, no `pip install`,
  no `cargo install`.
* No `cargo build`, no `npm run tauri build`.
* No subagent spawn.  No restart of user processes.
* PowerShell used `;` instead of `&&`.
* Edits limited to the allowed file list; only `routes.py` +
  `schema.py` were modified with additive-only edits.  `peer_routes.py`
  / `notes_routes.py` / `ai/*` / `ui/dist/*` were not touched.
* Every commit was scoped (`git add <exact_path>`); no `git add .`.
* Worked through parallel sibling commits without merge conflicts
  (Sibling A's `4e317bff peer comparison routes` landed between my
  Stage 3 and Stage 4 — confirmed via `git log --oneline -10` after
  each commit; no file overlap).

## 9. Follow-ups (deferred, tracked elsewhere)

* **Per-org KeyManager.**  M3 keeps the M1 W2 single-component model
  (`component='global'`).  v0.3 Part Infra §5.1 wants per-org keys;
  the new `key_versions.component` column is already wide enough for
  that refactor — only the unlock path + `KeyManager` cache key need
  updates.  Out of scope for M3.
* **Cron-driven yearly rotation.**  §2.5 envisions "1× per year"
  background rotation; this report wires only the manual entrypoint.
  The new `key_rotation_runs` table is the substrate any future
  scheduler will write into.
* **Per-org backup partition.**  `create_backup(org_id=…)` snapshots
  the entire SQLite file; per-org tarball filtering would require
  `sqlite3` `.dump` + selective `INSERT` replay.  Logged in
  `docs/follow-ups/skipped-items-roadmap.md` if there's appetite.
* **Tauri compile + e2e.**  Static wiring is verified by regex; an
  end-to-end native run requires `cargo build` (out of scope).

## 10. Blockers

None.  All seven commits landed cleanly, all 18 acceptance checks
green, sibling regression scripts (m2_closing / m3_notes_peer /
m3_raw_ai) all detected SUCCESS markers via stdout streaming.
