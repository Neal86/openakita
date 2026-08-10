# Hermes Extensions

Standalone extensions for **NousResearch/hermes-agent**. This package does not depend on the OpenAkita runtime, APIs, agents, or databases.

Current package version: **0.4.2**.

## Included

### Hermes Management Center

`hermes dashboard` gets one **Management Center** with four tabs:

- **Overview** — agents, projects when supported, task counts, gateway state, upcoming work, and partial-load errors.
- **Agents** — native Hermes Profile create/clone/rename/edit/use/export/delete plus workspace/model/provider/SOUL and gateway lifecycle management.
- **Projects** — native Hermes Project management when the installed Hermes exposes `hermes project`; otherwise the feature degrades cleanly without breaking Agents/Tasks/WeChat.
- **Tasks** — fleet-wide native Cron and Kanban management.

Hermes Profiles are treated as Agents. Hermes Projects remain native Hermes Projects; the extension does not create a second Agent, Project, scheduler, or task database.

### Windows WeChat Desktop

The plugin registers local Windows WeChat tools and a gateway platform. Automation uses Windows UI Automation rather than fixed screen coordinates and fails closed before outbound sends when the exact target chat cannot be proven.

Registered WeChat tools:

- `wechat_status`
- `wechat_list_chats`
- `wechat_get_unread_chats`
- `wechat_get_messages`
- `wechat_send_message`

### Hermes Task Center

Task Center reads native per-profile Cron state, Cron execution history and native Hermes Kanban surfaces. Mutations use Hermes CLI operations.

Registered task tools:

- `task_center_overview`
- `task_center_upcoming`
- `task_center_create`
- `task_center_update`
- `task_center_action`
- `task_center_history`

## v0.4.2 reliability hardening

### Transactional Windows install

`install.ps1` now stages and validates the new plugin before replacing the current installation:

1. Detect real Hermes capabilities.
2. Locate the **actual Python interpreter used by Hermes**, including `%APPDATA%\uv\tools\hermes-agent\Scripts\python.exe` used by normal `uv tool` installs.
3. Install dependencies only into that interpreter; it refuses to silently fall back to unrelated system Python.
4. Verify `yaml`, `croniter`, `pywinauto`, and `pyperclip` imports.
5. Build a staging plugin tree and generate the official Dashboard `dist/index.js` bundle.
6. Compile the staged Python code.
7. Back up the existing Hermes Extensions and WeChat platform.
8. Atomically replace both plugin directories and enable them.
9. Run installed-package doctor checks.
10. On any failure after replacement begins, automatically restore the previous plugin/platform files.

Python dependencies may remain installed after a failed upgrade, but the previous executable plugin code is restored.

### Fast compatibility probing

Hermes capability detection is cached in-process for 45 seconds. Dashboard API calls no longer spawn six `hermes <command> --help` subprocesses on every request. `/capabilities?refresh=true` forces an immediate re-probe after Hermes is upgraded.

### One Dashboard backend router

Compatibility handling now lives directly in `dashboard/plugin_api.py`; the duplicate `compat_api.py` router was removed. The manifest uses the Hermes v0.16-compatible standard:

```json
{
  "entry": "dist/index.js",
  "api": "plugin_api.py"
}
```

When `hermes project` is absent, Project reads return `supported: false` and Project mutations return a structured 409. Agent, Task, Dashboard and WeChat functionality remain available.

### Doctor modes

Before installation:

```powershell
.\doctor.ps1 -Preflight
```

Machine-readable preflight:

```powershell
.\doctor.ps1 -Preflight -Json
```

After installation:

```powershell
.\doctor.ps1 -Installed
```

Machine-readable installed report:

```powershell
.\doctor.ps1 -Installed -Json
```

The default mode is `-Installed` for backward compatibility.

## Install on Windows

From the extracted Hermes Extensions package:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\doctor.ps1 -Preflight
.\install.ps1
.\doctor.ps1 -Installed
```

For the user's observed Hermes v0.16.0 build where `profile`, `plugins`, `dashboard`, `cron`, and `kanban` are available but `project` is absent, installation is supported. Projects are disabled and automatically become available after upgrading to a Hermes build that exposes the native Project command.

Useful checks:

```powershell
hermes plugins list --plain --no-bundled
hermes dashboard
```

A first installation or change to Dashboard backend Python should restart only `hermes dashboard`. Frontend-only updates can be discovered through Dashboard plugin rescan. WeChat platform Python changes require restarting the relevant Hermes gateway, not reinstalling Hermes.

## Release package

The release workflow builds an isolated package:

```text
hermes-extensions-v0.4.2.zip
hermes-extensions-v0.4.2.zip.sha256
```

The ZIP root contains only the standalone Hermes extension tree. It excludes OpenAkita application code and tests, and includes a pre-built `dashboard/dist/index.js` expected by Hermes Dashboard.

## Validation

CI now covers:

- Python compilation, Ruff and pytest.
- Dashboard JavaScript syntax.
- Strict tool schemas and safety boundaries.
- Agent/Profile and Task Center regression tests.
- WeChat fail-closed automation unit tests.
- Hermes capability detection cache and forced refresh.
- PowerShell parser validation.
- A **real execution of `install.ps1` on Windows CI** against a fake Hermes v0.16-compatible command surface where native Projects are intentionally unavailable.
- Post-install file/discovery doctor checks.
- A deliberately failed upgrade proving the previous plugin is restored by transactional rollback.
- Release ZIP isolation and SHA256 generation.

A real WeChat acceptance test still requires native Windows with a logged-in WeChat client. CI cannot truthfully substitute for that device-level UI Automation test.

## Security notes

- Default and active Profiles are protected from deletion.
- Autonomous Agent tools do not expose Profile deletion or Gateway restart.
- Human Dashboard Gateway restart requires confirmation and post-command state verification.
- Profile/SOUL paths are validated against traversal.
- Provider credentials/API keys are not exposed by Management Center.
- WeChat outbound sends fail closed when the exact target cannot be verified.
- Keep Hermes Dashboard on localhost or behind trusted authentication/network controls.
