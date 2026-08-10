# Hermes Extensions

Standalone extensions for **NousResearch/hermes-agent**. This package does not depend on the OpenAkita runtime, APIs, agents, or databases.

Current package version: **0.4.0**.

## Included

### 1. Hermes Management Center

`hermes dashboard` gets one **Management Center** entry with four tabs:

- **Overview** — projects, agents, running gateways, scheduled/running/failed task counts, upcoming work, and partial-load errors
- **Agents** — create, inspect, rename, edit, select, start/restart gateways, edit SOUL/workspace/model/provider, and delete native Hermes Profiles
- **Projects** — create and manage native profile-scoped Hermes Projects, folders, primary repo, Kanban binding, active/archive state, and Workspace Agent selection
- **Tasks** — fleet-wide native Cron/Kanban Task Center

Hermes Profiles are treated as Agents; Hermes Projects remain first-class native Projects. The plugin does **not** create another Agent, Project, scheduler, or task database.

#### v0.4 management hardening

- Management reads use a single Agent snapshot that is reused while expanding Projects. A Project no longer recursively re-runs a full Agent scan.
- Workspace-to-Project matching uses normalized paths instead of raw string equality, including Windows case normalization.
- Partial profile/project failures are returned as `partial=true` plus scoped `errors[]` instead of silently appearing as empty data.
- Gateway start/stop/restart is followed by status polling. A command that exits successfully but does not reach the expected runtime state returns `ok=false` with an explicit verification warning.
- `gateway_restart` remains available from the human Dashboard with confirmation, but autonomous Hermes `agent_action` tools intentionally do not expose restart or delete.
- Dashboard forms stay open and preserve user input after failed create/update operations.
- Agent rename is wired end-to-end and the UI reopens the returned new profile name.
- Project edit UI only exposes fields the current Hermes Project CLI can actually mutate. Description/icon/color remain creation-time fields until Hermes exposes a stable edit command for them.
- Agent-to-Project UI wording is **Workspace Agent** because the relationship is computed from the Agent's native `terminal.cwd`, not stored as a multi-project membership database.
- Shared Hermes subprocess execution lives in `hermes_cli.py` and is used by Management and Task Center.
- Dashboard loads the maintainable `dashboard/src/index.js` directly; the stale generated JavaScript bundle was removed.

Native Agent/Profile operations use official Hermes commands such as:

- `hermes profile create/list/show/use/rename/delete/describe/export`
- profile-scoped `hermes config set terminal.cwd ...`
- profile-scoped `hermes config set model.provider ...`
- profile-scoped `hermes config set model.default ...`
- profile-scoped `hermes gateway start/stop/restart/status`

SOUL.md editing is the only direct profile-file mutation because Hermes does not currently expose a dedicated SOUL mutation command. The write is restricted to a validated profile home and replaced atomically.

Native Project operations use:

- `hermes project create/list/show`
- `hermes project add-folder/remove-folder`
- `hermes project rename/set-primary/use`
- `hermes project archive/restore/bind-board`

Projects are profile-scoped exactly as Hermes defines them. Workspace Agent selection sets the Agent's native `terminal.cwd` to the Project primary folder; the UI computes matching Agents from normalized workspace/folder paths.

Registered management tools:

- `management_overview`
- `agent_list`
- `agent_get`
- `agent_create`
- `agent_update`
- `agent_action`
- `project_list`
- `project_get`
- `project_create`
- `project_update`
- `project_action`

`management_overview` returns the same high-level management/task summary used by the Dashboard, including task counts and the next seven days of work.

### 2. Windows WeChat desktop tools

Registered Hermes tools:

- `wechat_status`
- `wechat_list_chats`
- `wechat_get_unread_chats`
- `wechat_get_messages`
- `wechat_send_message`

The connector uses native Windows UI Automation through `pywinauto`; it does not use fixed screen coordinates.

Send safety is fail-closed:

1. Search for the requested exact conversation name.
2. Reject the operation when multiple exact UIA search rows exist.
3. Open the single exact result when available.
4. Verify the visible conversation title in the content header.
5. Focus the message editor and paste the payload.
6. Verify the exact title again immediately before Enter.
7. Refuse the send if any verification step fails.

Duplicate identical sends to the same conversation are suppressed for 10 minutes by default. Message reads expose best-effort `text`, `sender`, `time`, and `direction` fields when the current WeChat UIA tree provides them. The gateway ignores a newest message positively identified as outbound so Hermes does not re-ingest its own reply.

### 3. Hermes Task Center

The Task Center reads native profile Cron state, native Cron execution SQLite history, native Kanban JSON surfaces, and `hermes kanban runs <id> --json` when available. All mutations use Hermes CLI operations.

Registered tools:

- `task_center_overview`
- `task_center_upcoming`
- `task_center_create`
- `task_center_update`
- `task_center_action`
- `task_center_history`

Task management supports all Hermes profiles/agents, recurring and one-shot Cron jobs, 24-hour / 7-day / 30-day future windows, expanded recurring occurrences, Kanban assignments, completed rows, Cron pause/resume/run/remove, Kanban archive, task creation, task detail and execution history.

Tool schemas are strict in v0.4: task actions are enum-constrained, unknown properties are rejected, field lengths are bounded, and autonomous Agent lifecycle actions exclude high-risk restart/delete.

## Install into local Hermes

From this directory on the machine that runs Hermes:

```powershell
./install.ps1
```

The installer resolves `HERMES_HOME`, performs a clean plugin code upgrade while preserving plugin runtime data, installs the general extension and WeChat gateway platform, installs shared dependencies plus Windows UI Automation dependencies, and enables plugins when `hermes` is available.

Useful checks:

```powershell
hermes plugins list
hermes plugins enable hermes-extensions
hermes plugins enable wechat-desktop
hermes dashboard
```

For continuous WeChat gateway routing, configure `gateway.platforms.wechat_desktop` or set `WECHAT_DESKTOP_AUTO_ENABLE=1`.

## Dependencies

`requirements.txt` contains shared Management/Task Center dependencies (`croniter`, `PyYAML`). `requirements-windows.txt` includes shared requirements plus `pywinauto` and `pyperclip`.

## Security notes

- Agent/Profile deletion refuses `default` and the currently selected sticky profile.
- Profile names and SOUL paths are validated to prevent path traversal.
- API keys are not exposed by the Management Center; provider credentials remain managed by Hermes.
- Autonomous Agent tools do not expose profile deletion or Gateway restart.
- Human Dashboard Gateway restart requires confirmation and runtime-state verification.
- The WeChat connector is local desktop automation, not an official Tencent API, and refuses outbound messages when it cannot prove the exact selected chat.
- Hermes dashboard plugin routes share the dashboard process security model. Keep the dashboard bound to localhost unless trusted authentication/network controls are configured.

## Validation

GitHub Actions validates:

- Python compilation and Ruff
- Management, Task Center, WeChat, and plugin-registration tests
- Agent rename and create-failure behavior
- Gateway command-success/state-failure behavior
- path normalization and traversal protection
- partial error reporting
- a Management snapshot call-budget regression that prevents Project-to-Agent N×M runtime probing
- strict tool schema safety contracts
- plugin/Platform/Dashboard version consistency
- Dashboard source JavaScript syntax
- Windows PowerShell installer syntax
- Windows compilation of shared CLI, WeChat, and Management modules

A real WeChat acceptance test still requires a native Windows machine with a logged-in WeChat client. CI cannot truthfully substitute for that device-level test.
