# Hermes Extensions

Standalone extensions for **NousResearch/hermes-agent**. This package does not depend on the OpenAkita runtime, APIs, agents, or databases.

Current package version: **0.2.0**.

## Included

### 1. Windows WeChat desktop tools

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

### 2. Hermes Task Center

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

The dashboard adds **Task Center** to `hermes dashboard` and supports:

- all Hermes profiles / agents
- recurring and one-shot Cron jobs
- fixed responsibilities grouped by profile
- 24-hour / 7-day / 30-day future windows
- expanded recurring occurrences
- Kanban assignments, including archived/completed rows on demand
- Cron pause / resume / run / remove
- Kanban archive and reassignment through edit
- manual Cron and Kanban creation
- task editing and detail view
- Cron and Kanban execution history
- loading, empty, error, busy, and success states
- persisted profile, date-range, and completed-task filters in browser local storage

## Install into local Hermes

From this directory on the Windows machine that runs Hermes:

```powershell
./install.ps1
```

The installer:

- resolves `HERMES_HOME` (default `~/.hermes`)
- performs a clean code upgrade while leaving plugin runtime data under `~/.hermes/plugin-data/`
- installs the general plugin into `~/.hermes/plugins/hermes-extensions/`
- installs the gateway platform into `~/.hermes/plugins/platforms/wechat-desktop/`
- installs shared Task Center dependencies plus Windows UI Automation dependencies
- tries Hermes-managed Python first, then system Python, with `uv` as a pip fallback
- enables the installed plugins when the `hermes` command is available

Then restart Hermes / gateway. Restart `hermes dashboard` or use the dashboard plugin rescan endpoint after changing dashboard plugin code.

Useful checks:

```powershell
hermes plugins list
hermes plugins enable hermes-extensions
hermes plugins enable wechat-desktop
hermes dashboard
```

For continuous WeChat gateway routing, configure `gateway.platforms.wechat_desktop` or set:

```powershell
$env:WECHAT_DESKTOP_AUTO_ENABLE = "1"
```

Optional environment variables:

- `WECHAT_DESKTOP_ALLOWED_CHATS` — comma-separated exact conversation names
- `WECHAT_DESKTOP_HOME_CHAT` — exact conversation for Cron delivery
- `WECHAT_DESKTOP_POLL_SECONDS` — unread polling interval
- `WECHAT_DESKTOP_AUTO_ENABLE` — auto-enable the platform

## Dependencies

Shared Task Center dependency:

```text
requirements.txt
```

Windows WeChat dependencies:

```text
requirements-windows.txt
```

`requirements-windows.txt` includes the shared requirements.

## Security notes

- The WeChat connector is local desktop automation, not an official Tencent API.
- It refuses outbound messages when it cannot prove the exact selected chat.
- Multiple exact-name search rows are treated as ambiguous and are not auto-selected.
- UI Automation trees can change across WeChat releases; run `wechat_status` and a `dry_run` send after a WeChat update.
- Hermes dashboard plugin routes share the dashboard process security model. Keep the dashboard bound to localhost unless you deliberately configure trusted network access/authentication.

## Validation

GitHub Actions validates:

- Python compilation
- Ruff
- unit tests for Task Center aggregation, profile scoping, recurrence, archived Kanban visibility, native Kanban run history, and WeChat send safety
- plugin manifests and version consistency
- gateway platform registration surface
- dashboard JavaScript syntax
- Windows PowerShell installer syntax
- Windows compilation of the WeChat automation modules

A real WeChat acceptance test still requires a native Windows machine with a logged-in WeChat client. CI cannot truthfully substitute for that device-level test.
