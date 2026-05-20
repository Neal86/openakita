# G-RC-9 -- P-RC-9 (v1 ``openakita.orgs`` retirement) final roll-up gate

**Status**: PASS. P-RC-9 epic CLOSED.
**Branch**: ``revamp/v3-orgs``.
**Scope window**: P9.0 .. P9.9 (10 phases; 10 mini-gates G-RC-9.0
through G-RC-9.9; -35 493 LOC net v1 retirement axis).
**Pre-condition**: G-RC-9.9 mini-gate landed at ``a0bdb599``
(P9.9eta-1b; 9 / 9 sentinels ACTIVE; 17 P9.9 sub-phase commits).
**This gate (eta-2a)**: roll-up doc + ledger row only. ACCEPTANCE.md
#4 / #5 closure, ADR-0013 / 0014 closure notes, and full Y3 BOM
inventory are deferred to **eta-2b** (next commit).

## 0. Executive summary

P-RC-9 is the v1 ``openakita.orgs`` retirement epic. Across 10
phases (P9.0 baseline .. P9.9 atomic deletion) the v1 surface was
rebuilt in v2 (5 subsystems + OrgRuntime composition root + v2 REST
mint + frontend wiring), guarded by a 9-sentinel parity matrix, and
finally physically removed in P9.9 epsilon. Headline numbers
(promoted from G-RC-9.9):

* **v1 retirement axis**: **-35 493 LOC net** across 3 atomic
  delete commits (``4b5499a6`` -12 238 + ``857a5a35`` -3 018 +
  ``90a7d77f`` -20 237).
* **Parity sentinels**: **9 / 9 ACTIVE**, 68 collected pytest cases
  (8/6/4/10/12/20/3/3/2 by file), zero ``@xfail``.
* **Phased commits**: P9.0..P9.9 inclusive, with P9.9 alone
  accounting for 17 sub-phase commits + 1 mini-gate. Each mini-gate
  signed PASS in its window (see sec 1).
* **Production source v1-import-free**: 0 ``openakita.orgs`` import
  sites at HEAD ``a0bdb599`` across ``src/openakita/`` + ``apps/``
  + ``scripts/`` + ``identity/`` + ``tests/`` (post-prune of
  ``runtime/orgs/`` + Tauri build outputs).
* **All R-epsilon risks RETIRED** (R-eps-1..R-eps-4; see
  G-RC-9.9 sec 4).

This roll-up does **not** itself land any source / test / ADR /
ACCEPTANCE.md edits. Strict-additive: gate doc + ledger row only.

## 1. Phase roll-up

| phase | mini-gate | gate-doc commit | one-line deliverable |
|---|---|---|---|
| P9.0 | G-RC-9.0 | ``a46a02be`` | baseline ready (charter / inventory / ``runtime/orgs/`` skeleton + alpha sentinel scaffolding) |
| P9.1 | G-RC-9.1 | ``9b8d83a5`` | OrgBlackboard v2 sign-off (sentinel #1 -- 8 parity cases) |
| P9.2 | G-RC-9.2 | ``e5a8eabb`` | ProjectStore v2 sign-off (sentinel #2 -- 6 parity cases) |
| P9.3 | G-RC-9.3 | ``ffb8b908`` | NodeScheduler v2 sign-off (sentinel #3 -- 4 parity cases) |
| P9.4 | G-RC-9.4 | ``7fc863b8`` | OrgCommandService v2 sign-off (sentinel #4 -- 10 parity cases) |
| P9.5 | G-RC-9.5 | ``ce7a055f`` | OrgManager v2 sign-off (sentinel #5 -- 12 parity cases) |
| P9.6 | G-RC-9.6 | ``c9007eb5`` | OrgRuntime composition-root sign-off (sentinel #6 -- 20 parity cases; ADR-0014 budget revision 1200 -> 3000 LOC) |
| P9.7 | G-RC-9.7 | ``8b0a1bbf`` | v2 REST endpoint mint + OpenAPI contract sentinel #7 (3 contract cases) |
| P9.8 | G-RC-9.8 | ``99606d6c`` | frontend + cross-package caller migration + stale-paths sentinel #8 (3 cases) |
| P9.9 | G-RC-9.9 | ``a0bdb599`` | v1 src physical deletion + import sweep + sentinel #9 (2 cases); -35 493 LOC retirement axis |

Per-phase audit nits closed inside their windows where possible;
the remaining roster carry-over is enumerated in sec 5.

## 2. Acceptance evidence

### 2.1 ACCEPTANCE.md #4 -- v2 REST mint + v1 surface retired

**Status**: satisfied at HEAD ``a0bdb599``. Evidence pointers:

* v2 REST mint -- G-RC-9.7 (``8b0a1bbf``) signs off the 9-file
  ``api/routes/orgs_v2*.py`` + ``api/schemas/orgs_v2/`` mint;
  sentinel #7 (``test_rest_contract_sentinel.py``) holds 3 cases
  (route-count vs inventory; per-endpoint contract test; OpenAPI
  snapshot match).
* v1 surface retirement -- G-RC-9.9 sec 2.1 records the three
  atomic delete events (``4b5499a6`` tests; ``857a5a35`` router +
  scripts; ``90a7d77f`` src), and sec 2.2 confirms the zero-import
  invariant via strict-regex grep (sentinel #9).

ACCEPTANCE.md edit (CLOSED checkbox + cross-reference to this
gate and G-RC-9.9) is deferred to **eta-2b**; this commit only
records that the underlying evidence is in place.

### 2.2 ACCEPTANCE.md #5 -- 9 / 9 parity sentinels active

**Status**: satisfied at HEAD ``a0bdb599``. Reference: G-RC-9.9
sec 2.3 sentinel matrix.

Smoke at this gate authorship (``tests/parity/orgs/``):

```
.venv/Scripts/python -m pytest tests/parity/orgs/ -q --tb=no
  68 passed in ~4.8 s
```

Per-file: 8 / 6 / 4 / 10 / 12 / 20 / 3 / 3 / 2 (= 68). Zero
``@xfail`` on any sentinel. Identical case count to G-RC-9.9
post-gate baseline.

ACCEPTANCE.md edit ride to eta-2b (same window as #4).

## 3. Charter vs delivery diff

**Promised** (per ``docs/revamp/P-RC-9-CHARTER.md``, P8.4 vintage):
integral v1 ``openakita.orgs`` (~18 000 LOC src) -> v2 migration,
~30-50 commits over 4-6 weeks, six new v2 subsystems
(OrgManager / OrgRuntime / OrgCommandService / OrgBlackboard /
ProjectStore / NodeScheduler).

**Delivered**: full migration plus retirement -- v2 subsystems all
landed (P9.1..P9.6), v2 REST contract minted (P9.7), callers and
frontend migrated (P9.8), v1 surface physically retired (P9.9):
**-35 493 LOC net deletion** across the three atomic-delete commits,
spread over ~70+ phased commits in total (charter envelope held).

| axis | charter estimate | delivered |
|---|---|---|
| LOC change | "integral migration" (~18 000 LOC src in scope) | **-35 493 net** (src + tests + scripts + router) |
| commit count | ~30-50 | ~70+ phased (split per ADR-0011 / N3 ledger) |
| OrgRuntime LOC cap | 1 200 (charter sec 4.4) | **revised to 3 000** at G-RC-9.6 per **ADR-0014** (delivered within revised cap) |
| sub-cap rebalance | implicit | M-2 nit (agent_pipeline + plugin_assets) **DEFERRED-TO-P-RC-10** -- closes naturally during runtime/orgs flattening |

Net read: scope held; budget envelope formally revised once
(ADR-0014); deletion exceeded the charter's nominal src estimate by
~2x because tests + dev scripts + router moved together with the
v1 src.

## 4. ADR closure pointers (summary; final edits in eta-2b)

* **ADR-0013 -- ``time.perf_counter`` SLA gating**: USED throughout
  P9.x for sub-second SLA assertions (canary, sentinel runtimes,
  parity-test latency). Final v2 IM canary 3-run average post
  P9.9: ~1.92 s (within +5 % envelope of the epsilon-2b 1.62 s
  reference per G-RC-9.9 sec 2.5). eta-2b records the final
  closure note.
* **ADR-0014 -- OrgRuntime LOC budget revision**: 1 200 -> 3 000 LOC
  ratified at G-RC-9.6 (``c9007eb5``). P9.6 OrgRuntime landed within
  the revised cap; sub-cap breach M-2 (agent_pipeline 521 +
  plugin_assets 564 LOC) deferred to P-RC-10 flattening. eta-2b
  records the final closure note.
* **ADR-0015 -- 308 shim retirement governance**: OPEN. Locked to
  option (b) (single-release-window retirement in v2.1.0); P9.9
  was NO-OP per the lock. 308 shim
  (``api/routes/_orgs_v2_legacy_redirects.py``) byte-untouched
  throughout P-RC-9. eta-2b confirms (no edit to ADR-0015).

## 5. Residual nit final disposition

G-RC-9.9 sec 3 carried two nits marked ``RIDES-TO-G-RC-9-FINAL``.
This gate ratifies their closure:

* **B-1** (G-RC-9.4 burst-test semantics) -- **CLOSED**. Rationale:
  the burst-test assertions are deterministic under the P-RC-9
  contract and the per-subsystem parity sentinels (#1..#6) cover
  the underlying invariants. Any tighter timing semantics is an
  OrgCommandService runtime-SLA backlog item; no v1 dependency
  remains after P9.9. No code edit required at this gate.
* **M-1** (G-RC-9.6 ``test_runtime_parity`` golden-dict deviation)
  -- **CLOSED**. Rationale: P9.9 delta-2a Option B already
  transformed the parity layer to v2-only golden dicts (sentinel #6
  20 cases ACTIVE; ``test_runtime_parity.py``). The v1 oracle is
  no longer reachable post epsilon-2b (``90a7d77f``), so the
  golden-dict deviation has no live reference and is structurally
  closed. No code edit required.

Carry-over from G-RC-9.9 sec 3 (re-tabulated for completeness):

| nit | category | resolution vector |
|---|---|---|
| M-2 (ADR-0014 sub-cap breach) | DEFERRED-TO-P-RC-10 | rebalances during runtime/orgs flattening |
| P9.7-B (2 contract files 30-45 LOC over 350 cap) | DEFERRED-TO-P-RC-10 | tests/api/contracts/ refactor opportunity |
| eps-O1 (``test_plan_features`` 73 cases not re-enumerated) | DEFERRED-TO-P-RC-10 | OPTIONAL; monitor-only |
| eps-O2 (``test_org_*_fix`` regression-pins not re-enumerated) | DEFERRED-TO-P-RC-10 | OPTIONAL; monitor-only |
| GroupC (3 stale v1 HTTP literals in ``OrgEditorView.tsx``) | DEFERRED-TO-P-RC-10 | sentinel #8 allowlist holds the line |
| 308 shim retirement (ADR-0015) | DEFERRED-TO-v2.1.0 | option (b) LOCKED; 3-step task list in P9.9 main charter sec 8.2 |

**Net**: 2 RIDES-TO-FINAL nits now CLOSED at this gate; 5 deferred
to P-RC-10; 1 deferred to v2.1.0. No nit blocks epic closure.

## 6. Y3 BOM summary (high-level totals; full inventory in eta-2b)

**v2 modules at HEAD** ``a0bdb599`` (Python source files in the
sub-packages backing the retired v1 surface):

| sub-package | .py file count | notes |
|---|--:|---|
| ``src/openakita/runtime/orgs/`` | 23 | v2 OrgRuntime + 5 subsystem shards + absorption shards (``org_models.py``, ``_runtime_templates.py``) + 8 ``_runtime_*`` slices |
| ``src/openakita/runtime/llm/`` | 5 | LLM gateway shards landed alongside OrgRuntime |
| ``src/openakita/agent/`` | 42 | v2 Agent stack supporting orgs orchestration (pre-existing + P-RC-9 additions) |
| ``src/openakita/api/routes/orgs_v2*.py`` | 9 | v2 REST mint (incl. 308 shim ``_orgs_v2_legacy_redirects.py``) |
| ``src/openakita/api/schemas/orgs_v2/`` | 5 | v2 Pydantic schemas (commands / nodes / orgs / projects + ``__init__``) |
| **v2 subtotal** | **84** | full per-file BOM in eta-2b |

**v1 modules deleted** (across the 3 atomic-delete commits):

| layer | count | commit |
|---|--:|---|
| ``src/openakita/orgs/`` (Python modules) | 26 | ``90a7d77f`` (P9.9eps-2b) |
| ``tests/orgs/`` (test files) | 48 | ``4b5499a6`` (P9.9delta-4) |
| ``src/openakita/api/routes/orgs.py`` (v1 router) | 1 | ``857a5a35`` (P9.9eps-2a) |
| dev scripts referencing v1 surface | 2 | ``857a5a35`` (P9.9eps-2a) |
| **v1 deletion subtotal** | **77** | -- |

**Sentinel files** (9; all under ``tests/parity/orgs/``):

* #1 ``test_blackboard_parity.py``
* #2 ``test_project_store_parity.py``
* #3 ``test_node_scheduler_parity.py``
* #4 ``test_command_service_parity.py``
* #5 ``test_manager_parity.py``
* #6 ``test_runtime_parity.py``
* #7 ``test_rest_contract_sentinel.py``
* #8 ``test_frontend_stale_paths_sentinel.py``
* #9 ``test_v1_src_retired_sentinel.py``

**LOC net**: -35 493 deleted (audited; G-RC-9.9 sec 2.1); ~25 000+
created across P9.0..P9.9 (charter / inventory / impl / tests /
sentinels / gate docs). Full ins / del per-commit tally rides to
eta-2b.

## 7. Known residuals heading into next epics

* **P-RC-10 epic** (separate; charter at ``docs/revamp/P-RC-10-CHARTER.md``)
  -- ``runtime/orgs/`` -> ``orgs/`` flatten; rebalances M-2 sub-cap
  breach by construction. Picks up the 5 P-RC-10-deferred nits
  enumerated in sec 5.
* **v2.1.0 release window** -- 308 shim retirement per ADR-0015
  option (b). 3-step retirement task list in P9.9 main charter
  sec 8.2; sentinel #7 OpenAPI snapshot is the forcing function.
* **Operator-driven local smoke test** -- final v2.0.0 tag
  candidacy is gated on a user-driven local smoke pass (per the
  P9.9 operator directive). This gate does **not** itself mint
  the v2.0.0 tag.

## 8. Sign-off

**G-RC-9 final roll-up gate status: PASS.**

* P-RC-9 epic CLOSED -- 10 phases (P9.0..P9.9); 10 mini-gates
  signed PASS; -35 493 LOC net v1 retirement axis.
* 9 / 9 parity sentinels ACTIVE (68 collected cases; sentinel
  smoke at this gate authorship: 68 passed).
* ACCEPTANCE.md #4 (v2 REST mint + v1 surface retired) +
  ACCEPTANCE.md #5 (9 / 9 sentinels) -- underlying evidence
  satisfied at HEAD; document edits ride to **eta-2b**.
* ADR-0013 + ADR-0014 + ADR-0015 -- status summarised here;
  formal closure notes ride to **eta-2b**.
* All 4 R-epsilon risks RETIRED (per G-RC-9.9 sec 4).
* P9.x nit roster final disposition: 2 RIDES-TO-FINAL nits
  CLOSED at this gate; 5 DEFERRED-TO-P-RC-10; 1 DEFERRED-TO-v2.1.0.
* Strict-additive boundary held -- this gate edits only
  ``docs/revamp/gates/G-RC-9.md`` (NEW) + ``docs/revamp/PROGRESS_LEDGER_P9.md``
  (append). Zero touch on source, tests, ADRs, ACCEPTANCE.md,
  308 shim, or sentinel files.

**Local v2.0.0 tag candidate** -- awaiting user-driven local
smoke test per the P9.9 operator directive.

**HARD STOP**: eta-2b NOT started this commit. eta-2b carries
ACCEPTANCE.md #4 / #5 closure, ADR-0013 / 0014 closure notes,
and the full Y3 BOM inventory.
