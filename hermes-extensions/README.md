# Hermes Extensions

Standalone extensions for **NousResearch/hermes-agent**. This package does not depend on the OpenAkita runtime, APIs, agents, or databases.

Current package version: **0.4.1**.

## Included

### 1. Hermes Management Center

`hermes dashboard` gets one **Management Center** entry with four tabs:

- **Overview** — agents, projects when supported, gateway state, task counts, upcoming work, and partial-load errors
- **Agents** — create, inspect, rename, edit, select, start/restart gateways, edit SOUL/workspace/model/provider, and delete native Hermes Profiles
- **Projects** — native Hermes Projects when the installed Hermes build exposes `hermes project`
- **Tasks** — fleet-wide native Cron/Kanban Task Center

Hermes Profiles are treated as Agents. The plugin does **not** create another Agent, Project, scheduler, or task database.

### Hermes v0.16 compatibility

v0.4.1 is designed to install safely on Hermes builds that have Profiles/Dashboard/plugins but do **not** yet expose the native `hermes project` command.

On such builds:

- Agents remain available.
- Tasks remain available.
- Dashboard remains available.
- Windows WeChat remains available.
- Projects return `supported: false` and are shown as unavailable instead of causing the Management Center to fail.
- Projects automatically become available after Hermes is upgraded to a build that exposes native `hermes project`.

The Dashboard manifest follows the Hermes v0.16 extension format and uses:

```json
{
  "entry": "dist/index.js",
  "api": "compat_api.py"
}
```

The source Dashboard remains under `dashboard/src/index.js`; installation/release packaging creates the pre-built `dashboard/dist/index.js` expected by Hermes.

### Management hardening

- Management uses a single Agent snapshot while expanding Projects, avoiding Project-to-Agent N×M runtime probing.
- Workspace/Project path matching is normalized, including Windows case normalization.
- Partial load failures return scoped errors instead of silently becoming empty data.
- Gateway start/stop/restart is followed by runtime-state verification.
- Autonomous Hermes Agent tools do not expose profile deletion or Gateway restart; the human Dashboard keeps restart behind confirmation.
- Failed Dashboard writes preserve forms and user input.
- Agent rename is wired end-to-end.
- Project edit UI only exposes fields Hermes can actually mutate.
- Shared Hermes subprocess handling lives in `hermes_cli.py`.

### 2. Windows WeChat desktop tools

Registered tools:

- `wechat_status`
- `wechat_list_chats`
- `wechat_get_unread_chats`
- `wechat_get_messages`
- `wechat_send_message`

The connector uses native Windows UI Automation through `pywinauto`, never fixed screen coordinates. Sending is fail-closed: exact chat selection and the visible title are verified before the send side effect, duplicate identical sends are suppressed, and `dry_run=true` verifies without pressing Enter.

### 3. Hermes Task Center

Registered tools:

- `task_center_overview`
- `task_center_upcoming`
- `task_center_create`
- `task_center_update`
- `task_center_action`
- `task_center_history`

The Task Center reads native Hermes Cron/Kanban state and uses official Hermes CLI mutations. It supports recurring/one-shot jobs, upcoming windows, execution history, pause/resume/run/remove, Kanban archive/assignment, and multi-profile aggregation.

## Install for testing

From the extracted `hermes-extensions-v0.4.1` directory in Windows PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

The installer:

1. Detects `plugins`, `dashboard`, `profile`, `project`, `cron`, and `kanban` capabilities from the **actual installed Hermes**.
2. Installs the plugin into `~/.hermes/plugins/hermes-extensions/`.
3. Builds `dashboard/dist/index.js` from the maintained Dashboard source.
4. Installs the WeChat platform into `~/.hermes/plugins/platforms/wechat-desktop/`.
5. Installs Python dependencies using the Hermes/uv Python environment when available.
6. Enables the plugins when supported.
7. Attempts a hot Dashboard rescan if the Dashboard is already running.
8. Verifies the installed package structure.

If `plugin_api.py`/`compat_api.py` changed or this is the first install, restart **only** `hermes dashboard`. If WeChat platform Python changed, restart the relevant Hermes Gateway. You do not need to reinstall the whole Hermes application.

Run the compatibility doctor any time:

```powershell
.\doctor.ps1
```

or after installation:

```powershell
~\.hermes\plugins\hermes-extensions\doctor.ps1
```

## Release package

`.github/workflows/hermes-extensions-release.yml` validates and packages only the standalone plugin directory as:

```text
hermes-extensions-v0.4.1.zip
hermes-extensions-v0.4.1.zip.sha256
```

The release archive contains the plugin itself and does not include OpenAkita runtime/application code. Branch builds upload the ZIP as a GitHub Actions artifact; tag builds named `hermes-extensions-v0.4.1` also publish a GitHub Release.

## Useful checks

```powershell
hermes plugins list --plain --no-bundled
hermes dashboard --status
hermes profile create --help
hermes project --help
```

A missing `hermes project` command is an expected supported compatibility mode in v0.4.1.

## Security notes

- Agent/Profile deletion refuses `default` and the currently selected sticky profile.
- Profile names and SOUL paths are validated against traversal.
- Provider credentials/API keys are not exposed by Management Center.
- Autonomous Agent tools do not expose profile deletion or Gateway restart.
- Human Dashboard Gateway restart requires confirmation and runtime-state verification.
- WeChat outbound sends fail closed if the exact conversation cannot be verified.
- Keep Hermes Dashboard bound to localhost unless trusted authentication/network controls are configured.

## Validation

CI checks Python compilation, Ruff, unit tests, capability detection, graceful Project fallback, strict tool schemas, Management call-budget regression, Dashboard JavaScript syntax, v0.16-compatible manifest fields, Windows PowerShell syntax, package isolation, release ZIP layout, and Windows module compilation.

A real WeChat acceptance test still requires native Windows with a logged-in WeChat client. CI cannot truthfully substitute for that device-level test.
