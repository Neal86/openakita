# OpenAkita — Skipped Items Roadmap

> Single source of truth for intentionally-deferred follow-ups uncovered by
> exploratory testing v10/v11 and the deep RCA report.

Tracks intentionally-deferred work items uncovered by exploratory
testing v10 / v11 (`_exploratory_test_report_v10.md`,
`_exploratory_test_report_v11.md`) and the deep RCA report
(`_skip_items_rca_v11.md`).

This document is the single source of truth that every TODO / NOTE /
ROADMAP block in the codebase about skipped items links back to. AI
agents working on plugin manifests, the legacy 308 shim, template
responses, or LLM tool budgets should consult this file FIRST, before
the upstream code or the RCA report.

Baseline commit: `65af00e7` (revamp/v3-orgs) — landed Fix-G1 through
Fix-G6 from RCA v11. Everything below is what was *deliberately not
done* in that wave because the change either needs evidence we don't
have yet (Phase 2 backfill, shim removal) or a deprecation window we
haven't paid for yet (Phase 3 schema escalation).

---

## A.1 Plugin tool_classes Phase 2 — incremental backfill

| Field | Value |
|-------|-------|
| Status | In progress (opportunistic). |
| Tool | `scripts/audit_tool_classes.py` (added with this roadmap). |
| Trigger | Plugin maintenance touches a manifest, OR monthly CI audit. |
| Cadence | 2–3 plugins per month — bundled with the plugin's other PR. |
| Exit criterion | tool_classes coverage ≥ 95 % across `plugins/**/plugin.json` + `plugins-archive/**/plugin.json`. |
| Owner | Plugin maintainers + reviewers. |
| Cross-ref | `_skip_items_rca_v11.md` §2.2, §2.5 (recommended scheme `A + C, B 短期降噪`). |

### Why this matters

`PluginManager.get_tool_class` reads `manifest.tool_classes` first
(`src/openakita/plugins/manager.py:300`) and falls back to the
classifier heuristics in `core/policy_v2/classifier.py` only when no
explicit mapping is found. Without explicit `tool_classes`, the
heuristics keep mis-classifying common patterns such as
`*_settings_get` (mis-classifies as UNKNOWN → quarantined under
safety-by-default) and `*_image_create` (mis-classifies as
MUTATING_SCOPED instead of NETWORK_OUT). RCA v11 §2.3 lists the
known false-positives.

### How to do it

1. Pick the plugin you're touching. Run:

   ```powershell
   .venv\Scripts\python.exe scripts\audit_tool_classes.py --plugin <id> --format table
   ```

2. The script prints a per-tool suggestion plus a confidence column
   (high / medium / low / unknown) plus evidence (name hits + input
   schema hints + description keywords).
3. Copy the **high-confidence** suggestions into the plugin manifest
   under `tool_classes`. Hand-review medium / low / unknown.
4. Optional: `--apply --plugin <id>` writes back only the
   high-confidence suggestions. Medium / low / unknown rows emit a
   review patch but are never written automatically.

### Pitfalls

- The heuristic only sees names + descriptions + (when present) input
  schema. It cannot know that an SDK function actually leaves the
  host. When in doubt, look at the handler implementation.
- `UNKNOWN` is the safety-by-default class — never apply blindly. A
  human must classify these.
- Do not regenerate the entire `tool_classes` block from the audit
  script — preserve manually-curated entries.

### DO NOT do yet

- Do NOT promote `tool_classes` from optional to required in
  `manifest.py` until coverage hits ≥ 95 %. That belongs to §A.2.

---

## A.2 Plugin manifest tool_classes Phase 3 — schema escalation

| Field | Value |
|-------|-------|
| Status | Planned for OpenAkita 2.0 major. |
| Prereq | §A.1 ≥ 95 % coverage + SDK codemod (`scripts/audit_tool_classes.py --apply`) is stable. |
| Migration | 3-release deprecation cycle (see below). |
| Cross-ref | `_skip_items_rca_v11.md` §2.5 Phase 3. |

### Migration path

| Release | Behaviour | `_validate_tool_classes_completeness` mode |
|---------|-----------|-------------------------------------------|
| N (current) | Tool-classes optional; classifier heuristics fill the gap. | `off` (stub already present in `installer.py`). |
| N+1 | WARN at install time when missing. | `warn` |
| N+2 (2.0 major) | ERROR at install time. Opt-out flag: `--allow-missing-classes`. | `error` |
| N+3 | Remove the opt-out flag. | `error` (no opt-out). |

### DO NOT do yet

- Do NOT flip the default mode away from `off` in this branch. Any
  plugin not yet covered by §A.1 will fail to install.
- Do NOT change the manifest schema to mark `tool_classes` `required`
  in `manifest.py` until coverage ≥ 95 % + the codemod is stable.

The stub `_validate_tool_classes_completeness` in
`src/openakita/plugins/installer.py` exists as the future hook
point — wire it from `install_from_path` / `install_from_url` /
`install_from_git` when ready.

---

## A.3 Legacy 308 redirect shim removal

| Field | Value |
|-------|-------|
| Status | Deprecation marker applied (commit `65af00e7`, Fix-G5). |
| Target | OpenAkita 2.1.0 minor. |
| Decision data | `GET /api/diagnostics/legacy-shim-stats` (added with this roadmap). |
| Exit criterion | `hits` for every shim path stays at 0 for ≥ 30 days past the `Sunset: 2026-12-01` header. |
| Cross-ref | `_skip_items_rca_v11.md` §3, `docs/adr/0015-308-shim-retirement-governance.md`. |

### Current state (recap)

The shim at `src/openakita/api/routes/_orgs_v2_legacy_redirects.py`
exposes nine paths under `/api/v2/orgs[/...]`. Eight of them are
already shadowed by `orgs_v2_runtime.router`; only
`POST /api/v2/orgs/templates/{id}/instantiate` is still effective.
Every response carries RFC 8594 `Deprecation: true` + `Sunset:
2026-12-01` headers.

### How the counter works

`_orgs_v2_legacy_redirects.py` keeps a thread-safe `Counter` keyed on
the requested path. Every shim handler calls `_record_shim_hit` before
issuing the 308. The counter survives process lifetime (in-memory),
not restarts — it is intentionally a low-cost observability primitive,
not a persistent metric. Pair with log scraping for long-window
evidence.

### Action steps when ready to remove

1. Poll `GET /api/diagnostics/legacy-shim-stats` daily; record
   `hits` per path.
2. After the 30-day Sunset window with `hits == 0` for every path,
   open a removal PR that:
   - Deletes `src/openakita/api/routes/_orgs_v2_legacy_redirects.py`
   - Deletes the `app.include_router(_orgs_v2_legacy_redirects.router)`
     line in `src/openakita/api/server.py` (see ROADMAP block above
     that line).
   - Drops the `get_shim_hit_stats` import from
     `src/openakita/api/routes/health.py` and the
     `/api/diagnostics/legacy-shim-stats` endpoint, or repurposes it.
3. Update `docs/adr/0015-308-shim-retirement-governance.md` with the
   final removal commit hash.
4. Move this section under `## Completed`.

### DO NOT do yet

- Do NOT delete the shim file or its include_router line in 2.0.x —
  the 30-day evidence window must elapse first.

---

## A.4 spec/runtime template response format unification

| Field | Value |
|-------|-------|
| Status | Design locked, implementation pending P9.7gamma. |
| Direction | Change spec endpoint from `{"templates": [...], "count": N}` envelope to a bare JSON array, matching the runtime endpoint. |
| Cross-ref | `_skip_items_rca_v11.md` §4.3. |

### Affected files

- `src/openakita/api/routes/orgs_v2.py::list_templates` (spec, currently envelope).
- `src/openakita/api/routes/orgs_v2_runtime_orgs.py::list_templates` (runtime, currently bare array — keep).
- `tests/api/contracts/test_orgs_v2_spec.py` (if any envelope assertion).
- `tests/api/contracts/test_orgs_v2.py` (runtime contract).

### Frontend impact

Zero. `apps/setup-center/src/api/orgs.ts` only talks to the runtime
endpoints. See the NOTE block at the top of that file.

### Action steps

1. Land the change in `list_templates` (spec) — return
   `[spec.to_jsonable() for spec in GLOBAL_REGISTRY.list()]`.
2. Update any contract test that pins the envelope shape.
3. Bump the spec response shape in `docs/api/openapi-surface.md`.
4. Drop the ROADMAP comment in `orgs_v2.py::list_templates`.
5. Move this section under `## Completed`.

### DO NOT do yet

- Do NOT change the runtime endpoint. Frontend depends on the bare
  array there.
- Do NOT add a third shape (e.g. `{"items": [...]}`); pick the runtime
  shape and converge.

---

## A.5 Lazy tool loading (deferred epic, NOT for this milestone)

| Field | Value |
|-------|-------|
| Status | Epic, not scheduled. |
| Cross-ref | `_skip_items_rca_v11.md` §1.4 (方案 C). |

### Trigger conditions (at least one must be met)

- Plugin count installed in a typical deployment > 30, OR
- Single main-chat turn cost in tokens > the threshold set by
  ops / billing, OR
- Single main-chat turn wall-clock > 20 s repeatedly attributable to
  schema delivery cost.

### ROI estimate

`-6 K token / turn` on the main chat when the lazy loader plus
`tool_search` round-trip pattern stabilises. Sub-agent benefit is
smaller (sub-agents already use a reduced set today).

### DO NOT do yet

- Only start this epic when at least one trigger above is met.
- The current stable tool set (Fix-G3 + Fix-G4 in `65af00e7`) is the
  agreed baseline — do not refactor `_effective_tools` or
  `_convert_tools_to_llm` without an explicit lazy-loading charter.
- Sub-agent tool isolation is already enforced via
  `_agent_tool_names`; do not regress that for the sake of lazy
  loading.

---

## How AI agents should use this file

When you (Claude / GPT / any other agent or human developer) are about
to modify ANY of the following, read the relevant section here AND the
linked RCA section FIRST:

| You are touching… | Read first |
|-------------------|------------|
| a plugin's `plugin.json` manifest | §A.1, run `scripts/audit_tool_classes.py` |
| `src/openakita/plugins/manifest.py` or `installer.py` | §A.2 |
| `src/openakita/api/routes/_orgs_v2_legacy_redirects.py` or `server.py` include_router for it | §A.3 |
| `src/openakita/api/routes/orgs_v2.py::list_templates` | §A.4 |
| `core/_agent_legacy.py::_effective_tools` or `core/_brain_legacy.py::_convert_tools_to_llm` | §A.5 + `_skip_items_rca_v11.md` §1 |

Before acting, read the relevant section here AND the linked RCA
section. Skipped items have explicit "DO NOT do yet" notes when
applicable; honour them unless the user explicitly asks for that
change with awareness of the deferral.

---

## How to check if an item is now ready

Each section above lists exit / trigger criteria. To check readiness:

- §A.1: run
  `python scripts/audit_tool_classes.py --all --format table` and look
  at the per-plugin `missing` column plus the overall coverage line.
- §A.2: same as §A.1; only ready when ≥ 95 % coverage.
- §A.3: hit `GET /api/diagnostics/legacy-shim-stats` and confirm
  `hits` is `{}` for ≥ 30 days past the `Sunset` header.
- §A.4: run the spec/runtime template contract diff (add one to
  `tests/api/contracts/test_orgs_v2_spec.py` if missing).
- §A.5: monitor `data/llm_debug/*.json` token totals; compare against
  trigger thresholds.

---

## Updates to this file

When you complete an item:

1. Move its section to `## Completed` at the bottom.
2. Record the merge date and commit hash.
3. Keep the section text intact (history matters for future audits).
4. Remove the now-obsolete TODO / ROADMAP blocks from the code that
   linked back to this file.

Do not delete history.

---

## Completed

_None yet._
