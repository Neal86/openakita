# P-RC-9 Execution Plan -- ``src/openakita/orgs/`` integral migration

> **Branch:** ``revamp/v3-orgs`` (forked from ``v2.0.0-rc2`` at
> ``594d5cb1``). Do NOT push; do NOT delete ``revamp/v2``; the
> ``v2.0.0-rc1`` / ``v2.0.0-rc2`` tags remain authoritative for
> any operator who needs the last stable v2 release while
> P-RC-9 is in flight.
>
> **Recon:** ``docs/revamp/P-RC-9-RECON.md`` (P9.0b + P9.0b2).
> Every number in this plan traces back to a section of the recon.
>
> **Layout:** this plan is grown across **three commits**
> (P9.0c -> sections 0..3, P9.0d -> sections 4..5, P9.0e ->
> sections 6..8) because the full document exceeds the 380-LOC
> commit_guard cap (N12, G-RC-5 audit clarification). Future
> readers should treat the three commits as one logical document.

## 0. North star + scope (what do we actually want)

### 0.1 The two-sentence summary

After P-RC-9 closes, ``src/openakita/orgs/`` no longer exists in
``revamp/v3-orgs``. Every behaviour it owned today is served by
``src/openakita/runtime/orgs/`` and a small set of preserved
leaf modules, every REST endpoint at ``/api/orgs/...`` has a
1:1 ``/api/v2/orgs/...`` peer (with the v1 surface either
deleted or shimmed for one release per the Q-B decision), and
ACCEPTANCE.md criteria 2 (wall-clock cancel) and 5 (UI default
port) are upgraded from Pass-with-caveat / Partial to Pass.

### 0.2 Explicit out of scope

* **No behaviour changes.** Every v2 subsystem must reproduce the
  v1 contract byte-for-byte where observable; deltas are limited
  to internal structure (dependency injection instead of
  back-references, factory-based singletons instead of
  ``OrgRuntime.get_*()`` accessors). The parity harness gates this.
* **No REST contract changes.** v2 endpoints are 1:1 with v1 --
  same path (with ``/v2`` prefix), same verb, same query/body
  schema, same response shape. Where the v1 endpoint accepts a
  free-form ``dict`` body, the v2 endpoint accepts the same.
  Schema tightening (Pydantic v2 model migrations, field
  deprecation, etc.) is deferred to a follow-on plan.
* **No feature additions.** P-RC-9 does not ship new endpoints,
  new schedule types, new tool handlers, new template kinds, or
  new IM verbs. Anything not in the v1 surface at ``v2.0.0-rc2``
  is out of scope and must be opened as a separate plan.
* **No frontend rewrites** beyond the default-port flip needed
  to close ACCEPTANCE.md #5 (UI ships its setup-center default to
  the v2 API). The full setup-center UI rewrite for v2 is a
  separate effort.
* **No migration of the 30+ existing v2 subsystems shipped in
  P-RC-0..P-RC-8.** The ``runtime/`` and ``agent/`` packages are
  considered done; P-RC-9 only adds the 6 charter subsystems
  alongside them.

### 0.3 What "done" looks like

* ``git ls-files src/openakita/orgs/ | wc -l`` -> **0** (after
  P9.9).
* ``git grep -nE 'from openakita\.orgs' -- src/openakita/`` ->
  **0** (after P9.8).
* ``git grep -nE 'from openakita\.orgs' -- tests/`` -> **0**
  except for any tests intentionally kept in ``tests/parity/orgs/``
  during a deprecation window (see Q-B).
* All 80 missing v2 REST endpoints land in P9.7 with
  ``test_orgs_v2_full.py`` coverage matching the v1 endpoint
  test counts (target: per-endpoint at least 1 happy-path case
  + 1 error-path case).
* ``scripts/revamp_loc_audit.py`` reports the 4 ``orgs/*``
  baseline rows at 0 LOC (after P9.9 the files do not exist;
  the audit script keeps the rows but reads 0 from disk and
  passes because ``current <= baseline`` trivially).
* ``pytest tests/runtime tests/agent tests/api tests/parity
  tests/unit/test_plugins`` -> baseline ``1123 + N`` (N = new
  v2 subsystem tests minus deleted ``tests/orgs/*`` tests; net
  delta projected positive because the 18 contract tests
  per-subsystem + the 6 parity suites add to roughly 200+
  cases while the deleted tests/orgs/ losses are roughly
  comparable -- exact number locked at G-RC-9.1 first sub-gate).
* ``v2.0.0-rc3`` tag cut locally with G-RC-9 sign-off.

## 1. Current truth (cite recon, not memory)

Every figure below is reproducible by the command in parentheses;
re-running on ``revamp/v3-orgs`` HEAD must yield identical output.

* **Branch state:** ``revamp/v3-orgs`` is at ``75aebde2`` after
  P9.0a/b/b2; before P-RC-9 work this branch is identical to
  ``revamp/v2`` HEAD ``594d5cb1`` (which is the ``v2.0.0-rc2``
  tag). ``git log --oneline revamp/v2..HEAD`` shows the P-RC-9
  commits only.
* **orgs/ package:** 26 files, 18 213 LOC
  (``Get-ChildItem src/openakita/orgs/ -File`` + sum). Top three
  giants: ``runtime.py`` (5 734 LOC, 31.5%), ``tool_handler.py``
  (3 183 LOC, 17.5%), ``templates.py`` (1 234 LOC, 6.8%) --
  combined 55.8% of the package.
* **v1 REST:** 89 endpoints, 2 145 LOC
  (``git grep -cE '^@router\.' -- src/openakita/api/routes/orgs.py``;
  ``wc -l`` on the same file). Verb split 39 POST / 36 GET / 7
  PUT / 7 DELETE.
* **v2 REST:** 9 endpoints split across ``orgs_v2.py`` (8) and
  ``orgs_v2_stream.py`` (1). Delta = 80 endpoints to add at P9.7.
* **Production callers:** 86 sites across 13 files; only 5 of
  the 13 are external to ``orgs/`` (api/routes/orgs.py,
  api/server.py, channels/gateway.py, api/routes/chat.py,
  core/_reasoning_engine_legacy.py). See recon ?1c table.
* **Test callers:** 216 sites across 48 ``tests/orgs/*.py``
  files + a handful of cross-cutting integration/unit tests.
* **Existing v2 ``runtime/orgs/``:** 3 files, 412 LOC
  (``__init__.py`` re-exports + ``store.py`` JsonOrgStore +
  ``sqlite_store.py``). Storage-only; zero of the 6 charter
  subsystems exists.
* **Baseline pytest:** 1123 passed / 1 skipped / 5 xfailed in
  ~10s; plus the 8-case v2 IM integration trio. LOC audit exits 0.

## 2. Risks and mitigations

The top 10 risks, ranked by ``probability x blast radius``. Each
has an owner phase and a concrete mitigation that the gate
criteria for that phase must verify.

### R1 -- 4-6 week timeline drift (probability HIGH, blast LARGE)

The charter projects 4-6 weeks of work across 30-50 commits.
Real history (P-RC-4 through P-RC-7) shows the rewrite cadence is
~5-10 commits per day under one engineer, and that estimate
holds *only* when each phase has a tight LOC budget and a hard
mini-gate. Drift comes from scope creep ("while I am in this
file I will also fix X") and from skipping the mini-gate
("just one more commit before I write the gate doc").

**Mitigation (P9.0 + every phase):** every phase has its own
``G-RC-9.x.md`` mini-gate that must be written before the next
phase opens. The gate doc takes ~30 minutes; it forces the
executor to re-read the plan section, re-count tests, and
re-state the next phase's entry conditions. The continuation
plan (P-RC-0..P-RC-8) used this and finished in roughly the
projected calendar; we copy the pattern verbatim.

### R2 -- caller deep-dependency on v1 internal types (HIGH, LARGE)

86 production callers and 216 test callers import from the legacy
``openakita.orgs`` package. The 32 ``.models`` imports and the
26 ``.project_store`` imports are the riskiest because callers
often build instances inline (``OrgProject(...)``,
``NodeSchedule(...)``) rather than going through a factory.
Renaming the module path breaks those instantiations even when
the data is identical.

**Mitigation (P9.1-P9.6 + P9.8):** v2 subsystems re-export the
v1 type names verbatim. Where the v1 dataclass has fields the
v2 implementation does not need, the v2 type still defines them
(with sensible defaults) so caller construction sites do not
have to change. The parity harness asserts ``OrgProject(...).
to_dict() == OrgProjectV2(...).to_dict()`` for the same inputs.
At P9.8 the import path rewrite is mechanical: one bulk sed pass
from ``openakita.orgs.X`` to ``openakita.runtime.orgs.X`` with a
test-suite green check after each batch.

### R3 -- cancel + checkpoint regression (MEDIUM, LARGE)

ACCEPTANCE.md #2 (Pass-with-caveat from P8.7-doc-fix) says the
IM-cancel-to-checkpoint pipeline finishes within 2 s but the
2 s figure is documentary (asyncio fixture default), not
measured. P-RC-9 reshapes the cancel path (cancel verb moves
from legacy ``channels/gateway.py`` -> v2 OrgCommandService).
A regression that pushes the pipeline above 2 s will silently
ship until a user notices.

**Mitigation (P9.4 + ADR-0013):** P9.4 ships a wall-clock budget
test that uses ``time.perf_counter()`` around the IM-cancel ->
checkpoint pipeline and asserts ``< 2.0 s`` on a CI-baseline
machine. The test is added to the main ``tests/runtime/`` set so
every commit on ``revamp/v3-orgs`` runs it. ADR-0013 records the
SLA contract.

### R4 -- SQLite data loss during migration (LOW, FATAL)

P9.1-P9.6 do not migrate operator data per se (the v2 stores
already exist as JsonOrgStore + SqliteOrgStore from P-RC-3), but
P9.5 (OrgManager) and P9.6 (OrgRuntime) touch the per-org dir
layout (``<data_dir>/orgs/<org_id>/...``) where the legacy
``manager.py`` keeps ``org.json`` + ``state.json`` + node
schedules. A botched layout migration can lose user state.

**Mitigation (P9.5 + P9.6):** ``scripts/backup_orgs_data.py``
runs before any layout change and archives the entire
``data/orgs/`` tree to ``data/orgs.legacy_p9/`` (mirror of the
pattern P-RC-7 used for ``data/orgs.legacy/``). The migration
script is **idempotent** and **dry-run-default** -- it prints
the file moves it would make and exits 0 unless ``--apply`` is
passed. ``docs/revamp/rollback.md`` is extended with a "P-RC-9
data restore" SOP.

### R5 -- circular imports between subsystems (MEDIUM, MEDIUM)

OrgManager <-> ProjectStore <-> OrgCommandService <-> OrgRuntime
all reference each other in v1 via direct imports + back-refs.
If we naively port that, the import graph cycles.

**Mitigation (P9.1-P9.6):** every subsystem exposes a small
``Protocol`` for its public surface (e.g.
``OrgManagerProtocol``, ``CommandDispatcherProtocol``).
Cross-subsystem references are typed via the Protocol, not the
concrete class, and instances are injected at construction time
(not imported). The DAG in recon ?1b is acyclic; honour it.

### R6 -- REST contract drift (MEDIUM, MEDIUM)

The 80 endpoints P9.7 must mint each have specific query-string
parsing, response-shape quirks, and error-code mapping rules.
"Same shape" can silently regress when the v2 implementation
uses a different dict ordering or omits a field that v1 always
sets to ``None``.

**Mitigation (P9.7):** every v2 endpoint ships with a contract
test that records the v1 response shape (golden JSON file under
``tests/api/golden/orgs_v1/<endpoint>.json``) and asserts the
v2 response matches. The golden files are captured before P9.7
work starts (a recon sub-step in P9.7). The 1:1 contract is then
machine-enforced.

### R7 -- ``tool_handler.py`` (3 183 LOC, 66 methods) folding into OrgRuntime (MEDIUM, MEDIUM)

The legacy tool_handler is a single class with 66 methods, each
implementing one of 33 ``org_*`` tools. Folding it into
OrgRuntime risks exploding OrgRuntime past the 1 200 LOC budget.

**Mitigation (P9.6):** ``tool_handler.py`` becomes its own
file ``runtime/orgs/tool_handler.py`` with the OrgToolHandler
class preserved verbatim (P-RC-4/5/6 pattern: copy then refactor
in-place). OrgRuntime gets a single ``handle_org_tool()``
delegate method that calls into the handler. The handler does not
count against OrgRuntime's LOC budget; it tracks against the
``orgs/tool_handler.py`` baseline (currently 3 474; once moved
to ``runtime/orgs/tool_handler.py`` the baseline transfers).

### R8 -- ``models.py`` field-level divergence (LOW, MEDIUM)

The 21 dataclasses in ``orgs/models.py`` are the canonical
shape for serialized data on disk. If P9.5 or P9.6 introduces
a v2 dataclass with one extra field, every existing
``data/orgs/<id>/projects.json`` becomes "stale" and
deserialization may fail.

**Mitigation (P9.5):** v2 types are **field-equivalent** to v1.
The migration is a rename, not a shape change. JSON round-trip
test cases are added at P9.5 (round-trip 100 sample blobs).

### R9 -- ``tests/orgs/`` deletion regret (LOW, LARGE)

48 test files, 216 import sites. If P9.9 mechanically deletes
them and a behavioural regression slips in (a test that proved
some invariant the v2 subsystem also relies on), nobody finds
out until a user hits it.

**Mitigation (P9.8 + P9.9):** before deletion, every legacy test
that exercises a behaviour the v2 surface still owns is
**migrated** (re-pointed) to the v2 module path. Only tests that
exercise legacy implementation detail (e.g. private
``_CachedAgent`` LRU eviction) are dropped. The migration audit
is the first sub-phase of P9.9 (``P9.9a-audit``).

### R10 -- frontend default-port flip breakage (LOW, MEDIUM)

ACCEPTANCE.md #5 Partial -> Pass requires the setup-center UI
to ship with the v2 default port. The Tauri / Vite build
artifact is what end users get; a typo in the env var or the
build config silently ships a broken default.

**Mitigation (P9.7):** P9.7 includes a build-artifact test that
loads ``dist-web/index.html``, parses the embedded
``BUILD_INFO`` JSON, and asserts the v2 port is present. The
test runs in CI on every commit, not just at release.

## 3. Drift-prevention discipline

This phase inherits every guardrail the continuation plan
P-RC-0..P-RC-8 used. The mechanics:

### 3.1 commit_guard (380 WARN / 400 REJECT)

``.venv/Scripts/python.exe scripts/revamp_commit_guard.py
--staged`` MUST run before every ``git commit --trailer "Co-authored-by: Cursor <cursoragent@cursor.com>"``. The script
counts hand-written LOC across the staged diff
(``git diff --cached --numstat``), skips auto-generated files
(``package-lock.json``, ``*.lock``, ``*.svg``,
``docs/revamp/*.json`` baselines), warns at 380, rejects at
400. Source of truth: ``WARN_THRESHOLD = 380``,
``REJECT_THRESHOLD = 400`` in the script (P-RC-2 T1 + P-RC-5
N12 clarification).

### 3.2 LOC audit gate

``.venv/Scripts/python.exe scripts/revamp_loc_audit.py`` MUST
exit 0 before every commit. The script reads
``docs/revamp/LOC_BASELINE.json`` and compares against current
LOC for the 15 tracked files. P-RC-9 extends the baseline:

* When a legacy ``orgs/*.py`` file is moved to
  ``runtime/orgs/*.py`` (P-RC-4..7 pattern: ``git mv X
  _X_legacy``), the legacy path baseline is preserved at its
  current LOC (so it can only shrink) and the new path gets a
  fresh baseline equal to the moved LOC.
* When a legacy file is deleted (P9.9), its baseline row is
  removed in the same commit.
* The four ``orgs/*`` rows currently tracked (``runtime.py``
  6355, ``tool_handler.py`` 3474, ``templates.py`` 1266,
  ``messenger.py`` 651) drop to 0 as each phase lands.

### 3.3 Sentinel / facade detection per v2 subsystem

``tests/parity/test_no_facade.py`` already scans
``agent/{core,reasoning,brain,tools,context}.py`` for the
"only re-export from openakita.core.X" anti-pattern. P-RC-9
extends the scan to ``runtime/orgs/{blackboard,project_store,
node_scheduler,command_service,manager,runtime}.py`` so each
new v2 subsystem is verified to have a real implementation,
not a thin shim around the legacy module.

### 3.4 Ledger row per commit (N3)

Every commit on ``revamp/v3-orgs`` MUST append a row to
``docs/revamp/PROGRESS_LEDGER_P9.md`` **in the same commit**.
``git add docs/revamp/PROGRESS_LEDGER_P9.md`` before
``git commit --trailer "Co-authored-by: Cursor <cursoragent@cursor.com>"``. No "the next commit will backfill the hash"
loophole.

### 3.5 Commit message format (N5 + continuation plan ?0.4)

* English conventional commit title, <= 72 chars.
* Blank line.
* Why paragraph (2-3 sentences explaining the motivation, NOT
  the what -- the diff shows the what).
* ADR refs + plan section refs.
* ``Files:`` footer listing each touched path with a
  one-phrase note.
* Delivered via Python tempfile (``Path("commit_msg.tmp").
  write_text(msg, encoding="utf-8")`` then ``git commit --trailer "Co-authored-by: Cursor <cursoragent@cursor.com>" -F
  commit_msg.tmp``). NEVER PowerShell ``Out-File -Encoding
  utf8`` (which prepends a UTF-8 BOM and corrupts the subject
  line; N5).
* No ``--amend`` after a commit has lived on the branch for
  > 1 hour (continuation plan ?0.4).

### 3.6 Pause every 5 commits

Every 5 commits, the executor MUST stop and re-read:

1. The latest section of this plan.
2. ``docs/revamp/PROGRESS_LEDGER_P9.md`` (all rows so far).
3. ``docs/revamp/P-RC-9-RECON.md`` for the relevant subsystem.
4. The active ADR (0011 / 0012 / 0013).

Then write a 1-line ``# still-aligned check at commit N`` note
to the ledger. P-RC-5 found this was the single most effective
drift-prevention tool.

<!-- P9.0c ends here. P9.0d appends sections 4 + 5. -->
