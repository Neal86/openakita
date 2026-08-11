# Hermes Extensions

Standalone extensions for **NousResearch/hermes-agent**. This package does not depend on the OpenAkita runtime, APIs, agents, or databases.

Current package version: **0.5.0**.

## Hermes Management Center v0.5.0

`hermes dashboard` gets one complete **Management Center** with five tabs:

- **Overview** — Agent/runtime/task counters, upcoming work, Project capability state, WeChat Gateway health, and scoped partial-load errors.
- **Agents** — native Hermes Profile create/clone/rename/edit/use/export/delete, workspace/model/provider/SOUL management, plus Gateway start/stop/restart/status.
- **Projects** — native Hermes Project create/use/archive/restore, folder add/remove/set-primary, board binding and Workspace Agent assignment. On Hermes builds without `hermes project`, the UI explicitly shows an unsupported state and disables creation instead of allowing 409 failures.
- **Tasks** — searchable/filterable native Cron and Kanban management with create/edit, Cron pause/resume/run/delete, Kanban assignment/priority/archive, upcoming occurrences and execution history.
- **WeChat** — persisted Gateway health, manual desktop connectivity check, recent/unread chats and a fail-closed **dry-run only** test that never presses Enter.

The Dashboard now uses real responsive dialogs rather than appending create/edit cards at the bottom of the page. Search/filter controls, loading/empty/error/unsupported states, responsive mobile layouts and action feedback are included.

### UI safety

The Overview reads only persisted WeChat Gateway health and does **not** focus the WeChat window. Desktop UI Automation is triggered only from explicit WeChat-page actions such as **Check desktop** or **Run dry test**.

The Management Center never exposes a casual one-click real WeChat send button. The built-in UI test path calls `dry_run=true`, verifies the exact conversation, types the payload and clears it without pressing Enter.

## Windows WeChat Desktop

The plugin registers local Windows WeChat tools and a Gateway platform. Automation uses Windows UI Automation rather than fixed coordinates and fails closed before outbound sends when the exact target conversation cannot be proven.

Registered tools:

- `wechat_status`
- `wechat_list_chats`
- `wechat_get_unread_chats`
- `wechat_get_messages`
- `wechat_send_message`

For known group conversations, configure exact names with `WECHAT_DESKTOP_GROUP_CHATS` (comma separated) or platform `extra.group_chats`. Those conversations enter Hermes with `chat_type="group"`; other chats remain `dm` unless explicitly configured.

### Concurrency and health hardening

The hardened `wechat/runtime.py` serializes UI operations across threads and processes. The exclusive transaction covers chat selection, exact-target verification, paste, final verification, Enter/dry-run cleanup and duplicate-send state. Lock timeout fails closed.

Gateway polling persists `healthy`, `degraded`, `failed` or `stopped` state plus consecutive failures, last error and last successful poll. Repeated UIA failures back off exponentially; recovery resets health.

## Hermes Task Center

Task Center v3 reads native per-profile Cron state/history plus Hermes Kanban surfaces and uses Hermes CLI for mutations.

Registered tools:

- `task_center_overview`
- `task_center_upcoming`
- `task_center_create`
- `task_center_update`
- `task_center_action`
- `task_center_history`

Upcoming scheduling is globally fair: every scheduled task gets first-occurrence visibility before high-frequency recurring jobs fill the remaining result budget. Cron execution status is queried in batches with one SQLite connection per Profile and only the latest run per job returned.

## Agents and Projects

Hermes Profiles are treated as Agents; Hermes Projects remain native profile-scoped Projects. The extension does not create a second Agent, Project, scheduler or task database.

When `hermes project` is absent (as observed on Hermes v0.16.0), Project API reads return `supported: false`, mutations return structured 409 responses, Project model tools are not registered, and the Dashboard shows the unsupported state without exposing create controls. Agents, Tasks and WeChat remain available.

## Install on Windows

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\doctor.ps1 -Preflight
.\install.ps1
.\doctor.ps1 -Installed
```

Useful checks:

```powershell
hermes plugins list --plain --no-bundled
hermes dashboard
```

The installer detects the actual Hermes Python interpreter, verifies dependencies, stages/compiles the new plugin, backs up the existing extension/WeChat platform/config, atomically replaces code, enables plugins and runs installed doctor checks. Failed upgrades restore plugin files and Hermes plugin configuration.

A first installation or Dashboard backend Python change should restart only `hermes dashboard`. Frontend-only updates can use Dashboard rescan. WeChat platform/runtime Python changes require restarting the relevant Gateway.

## Doctor modes

```powershell
.\doctor.ps1 -Preflight
.\doctor.ps1 -Preflight -Json
.\doctor.ps1 -Installed
.\doctor.ps1 -Installed -Json
```

The default mode is `-Installed`.

## Release package

The release workflow builds:

```text
hermes-extensions-v0.5.0.zip
hermes-extensions-v0.5.0.zip.sha256
```

The archive contains only the standalone Hermes extension tree, excludes OpenAkita application code/tests, and contains pre-built `dashboard/dist/index.js` and `dashboard/dist/style.css`.

## Validation

CI covers Python compilation, Ruff, pytest, Dashboard JavaScript syntax, v0.5.0 UI contract checks, strict Dashboard request bodies, capability-aware Project UI behavior, full Agent/Project/Task action surfaces, WeChat Dashboard routes/dry-run safety, responsive-dialog CSS, fair Task scheduling, batched Cron history, cross-process WeChat locking, polling health/backoff, group-chat classification, real Windows `install.ps1` execution, doctor checks, rollback of plugin files/config and Release ZIP isolation/SHA256 generation.

A real WeChat acceptance test still requires native Windows with a logged-in WeChat client. CI cannot substitute for device-level UI Automation testing.

## Security notes

- Default and active Profiles are protected from deletion.
- Autonomous Agent tools do not expose Profile deletion or Gateway restart.
- Human Dashboard Gateway restart requires confirmation and state verification.
- Profile/SOUL paths are validated against traversal.
- Provider credentials/API keys are not exposed by Management Center.
- WeChat outbound sends fail closed when exact-target verification or the cross-process UI lock cannot be obtained.
- The Management Center exposes only a WeChat dry-run test, not an unguarded real-send UI.
- Keep Hermes Dashboard on localhost or behind trusted authentication/network controls.
