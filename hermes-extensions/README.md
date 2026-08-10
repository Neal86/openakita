# Hermes Extensions

Standalone extensions for **NousResearch/hermes-agent**. This directory does not depend on OpenAkita runtime, APIs, agents, or databases.

## Included

### 1. Windows WeChat desktop tools

Registered Hermes tools:

- `wechat_status`
- `wechat_list_chats`
- `wechat_get_unread_chats`
- `wechat_get_messages`
- `wechat_send_message`

The connector uses Windows UI Automation through `pywinauto`. It never uses fixed screen coordinates. Before a send side effect it opens the requested conversation, verifies the visible conversation title, focuses the lower message editor, and verifies the title again. If target verification fails, sending is refused.

Duplicate identical sends to the same conversation are suppressed for 10 minutes by default.

Windows dependencies:

```powershell
python -m pip install -r requirements-windows.txt
```

### 2. Hermes Task Center

The task center is a management layer over native Hermes state. It does **not** implement another scheduler or task database.

It reads:

- Default profile and `~/.hermes/profiles/*`
- Each profile's native `cron/jobs.json`
- Each profile's native `cron/executions.db`
- Shared native Hermes Kanban via `hermes kanban ... --json`

All mutations are performed through the official Hermes CLI (`hermes cron ...`, `hermes kanban ...`).

Registered tools:

- `task_center_overview`
- `task_center_upcoming`
- `task_center_create`
- `task_center_update`
- `task_center_action`
- `task_center_history`

The dashboard adds **Task Center** to `hermes dashboard` and shows:

- all Hermes profiles/agents
- recurring and one-shot jobs
- fixed responsibilities grouped by profile
- next 24 hours / 7 days / 30 days
- expanded future occurrences for recurring jobs
- Kanban assignments
- pause/resume/run actions for Cron
- manual creation of Cron and Kanban tasks

## Install into local Hermes

From this repository directory:

### PowerShell

```powershell
./install.ps1
```

Or manually:

```powershell
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $HOME ".hermes" }
$Target = Join-Path $HermesHome "plugins/hermes-extensions"
New-Item -ItemType Directory -Force -Path $Target | Out-Null
Copy-Item -Recurse -Force ./* $Target
python -m pip install -r (Join-Path $Target "requirements-windows.txt")
```

Then restart Hermes / the gateway and rescan the dashboard plugin:

```powershell
hermes plugins list
hermes plugins enable hermes-extensions
hermes dashboard
```

Dashboard backend plugin routes are mounted at dashboard startup, so restart `hermes dashboard` after changing `dashboard/plugin_api.py`.

## Safety notes

- The WeChat connector is local desktop automation, not an official Tencent API.
- It fails closed when it cannot prove the selected chat title.
- UI Automation trees can change across WeChat releases; use `wechat_status` and a `dry_run` send after updating WeChat.
- Do not expose an unauthenticated Hermes dashboard to a public network; plugin backend APIs run inside the dashboard process.

## Validation

The branch includes Python compile checks, unit tests for task aggregation/profile scoping, plugin manifest checks, and JS syntax checking in GitHub Actions. Real WeChat UI tests require a Windows machine with a logged-in WeChat client and therefore remain an on-device acceptance test.
