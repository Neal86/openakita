# Hermes Extensions

Standalone extensions for **NousResearch/hermes-agent**. This package does not depend on the OpenAkita runtime, APIs, agents, or databases.

Current package version: **0.3.0**.

## Included

### 1. Hermes Management Center

`hermes dashboard` gets one **Management Center** entry with four tabs:

- **Overview** — projects, agents, running gateways, scheduled/running/failed task counts, and upcoming work
- **Agents** — create, inspect, edit, select, start/restart gateways, edit SOUL/workspace/model/provider, and delete native Hermes Profiles
- **Projects** — create and manage native profile-scoped Hermes Projects, folders, primary repo, Kanban binding, active/archive state, and Agent workspace assignment
- **Tasks** — the existing fleet-wide Cron/Kanban Task Center

Hermes Profiles are treated as Agents; Hermes Projects remain first-class native Projects. This plugin does **not** create another Agent or Project database.

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

Projects are profile-scoped exactly as Hermes defines them. Agent-to-Project assignment is represented by the Agent's native `terminal.cwd`; the UI computes Project membership from that workspace instead of storing a parallel assignment database.

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

Duplicate identical sends to the same conversation are suppressed for 10 minutes by default. Message reads expose best-effort `text`, `sender`, `time`, and `direction` fields when the current WeChat UIA tree provides them.

The gateway platform adapter lives under `platforms/wechat-desktop/` and can continuously route unread chats into Hermes. An optional exact-name allow-list is supported with `WECHAT_DESKTOP_ALLOWED_CHATS`.

### 3. Hermes Task Center

The Task Center is a management layer over native Hermes state. It does **not** implement a second scheduler or task database.

It reads:

- the default Hermes profile and `~/.hermes/profiles/*`
- each profile's native `cron/jobs.json`
- each profile's native `cron/executions.db`
- shared native Hermes Kanban through `hermes kanban ... --json`
- native Kanban attempt history through `hermes kanban runs <id> --json` when supported

All mutations use official Hermes CLI operations (`hermes cron ...`, `hermes kanban ...`). The Kanban history path keeps a compatibility fallback for older Hermes builds that do not yet expose `kanban runs`.

Registered tools:

- `task_center_overview`
- `task_center_upcoming`
- `task_center_create`
- `task_center_update`
- `task_center_action`
- `task_center_history`

Task management supports all Hermes profiles/agents, recurring and one-shot Cron jobs, 24-hour / 7-day / 30-day future windows, expanded recurring occurrences, Kanban assignments, completed rows, Cron pause/resume/run/remove, Kanban archive, task creation, task detail and execution history.

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
- The WeChat connector is local desktop automation, not an official Tencent API, and refuses outbound messages when it cannot prove the exact selected chat.
- Hermes dashboard plugin routes share the dashboard process security model. Keep the dashboard bound to localhost unless trusted authentication/network controls are configured.

## Validation

GitHub Actions validates Python compilation, Ruff, unit tests for Task Center/WeChat/Management Center, plugin manifests and version consistency, management API/dashboard surfaces, JavaScript syntax, Windows PowerShell installer syntax, and Windows compilation of WeChat + management modules.

A real WeChat acceptance test still requires a native Windows machine with a logged-in WeChat client. CI cannot truthfully substitute for that device-level test.
