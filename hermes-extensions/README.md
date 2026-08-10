# Hermes Extensions

Standalone extensions for **NousResearch/hermes-agent**. This package does not depend on the OpenAkita runtime, APIs, agents, or databases.

Current package version: **0.4.4**.

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

Registered WeChat tools: `wechat_status`, `wechat_list_chats`, `wechat_get_unread_chats`, `wechat_get_messages`, and `wechat_send_message`.

### Hermes Task Center

Task Center reads native per-profile Cron state, Cron execution history and native Hermes Kanban surfaces. Mutations use Hermes CLI operations.

Registered task tools: `task_center_overview`, `task_center_upcoming`, `task_center_create`, `task_center_update`, `task_center_action`, and `task_center_history`.

## v0.4.4 hardening

### Fully transactional Windows install

`install.ps1` detects the real Hermes command surface and the actual Python interpreter used by Hermes, including `%APPDATA%\uv\tools\hermes-agent\Scripts\python.exe`. It refuses unrelated system-Python fallback, verifies shared and Windows UI dependencies, builds and compiles a staging tree, backs up the existing plugin, WeChat platform and `config.yaml`, atomically replaces the code, enables the plugins, runs installed doctor checks, and restores both files and Hermes plugin configuration if the upgrade fails.

Python packages installed into the Hermes environment are intentionally not uninstalled during rollback; executable plugin code and Hermes enablement configuration are restored.

### Runtime compatibility and performance

Hermes capability detection is cached in-process for 45 seconds. `/capabilities?refresh=true` forces a re-probe. Explicit invalid Hermes executable paths are rejected instead of being reported as available.

Dashboard backend dynamic modules are registered in `sys.modules` before execution. This is required on Python 3.11 for `@dataclass` modules using postponed annotations and prevents the import-time `NoneType.__dict__` failure that can otherwise break `plugin_api.py`.

Dashboard request models now use Pydantic v2 `extra="forbid"` so unknown write fields are rejected instead of silently ignored. Hermes v0.16.0 itself pins Pydantic 2.x, so this remains compatible with the user's installed release.

Compatibility handling lives in the single `dashboard/plugin_api.py` router. The manifest uses:

```json
{
  "entry": "dist/index.js",
  "api": "plugin_api.py"
}
```

When `hermes project` is absent, Project reads return `supported: false`, mutations return a structured 409, and model-facing Project tools are not registered. Dashboard Project support can appear after an upgrade and capability refresh; Project tools require the Hermes/plugin process to restart or reload after the upgrade.

### Doctor modes

```powershell
.\doctor.ps1 -Preflight
.\doctor.ps1 -Preflight -Json
.\doctor.ps1 -Installed
.\doctor.ps1 -Installed -Json
```

The default mode remains `-Installed`.

## Install on Windows

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\doctor.ps1 -Preflight
.\install.ps1
.\doctor.ps1 -Installed
```

The observed Hermes v0.16.0 environment with `profile`, `plugins`, `dashboard`, `cron`, and `kanban` but no `project` is supported. Agents, Tasks and WeChat remain active while Projects degrade cleanly.

Useful checks:

```powershell
hermes plugins list --plain --no-bundled
hermes dashboard
```

A first installation or Dashboard backend Python change should restart only `hermes dashboard`. Frontend-only updates can use Dashboard rescan. WeChat platform Python changes require restarting the relevant Hermes gateway, not reinstalling Hermes.

## Release package

The release workflow builds:

```text
hermes-extensions-v0.4.4.zip
hermes-extensions-v0.4.4.zip.sha256
```

The archive contains only the standalone Hermes extension tree, excludes OpenAkita application code and tests, and includes the pre-built `dashboard/dist/index.js` expected by Hermes Dashboard.

## Validation

CI covers Python compilation, Ruff, pytest, Dashboard JavaScript syntax, strict schemas and API bodies, Profile/Task regression tests, WeChat fail-closed tests, capability cache and invalid-binary checks, Project-tool conditional registration, PowerShell parsing, real Windows execution of `install.ps1` against a v0.16-compatible fake Hermes without Projects, post-install doctor checks, failed-upgrade rollback of both plugin files and `config.yaml`, and release ZIP isolation/SHA256 generation.

A real WeChat acceptance test still requires native Windows with a logged-in WeChat client. CI cannot substitute for device-level UI Automation testing.

## Security notes

- Default and active Profiles are protected from deletion.
- Autonomous Agent tools do not expose Profile deletion or Gateway restart.
- Human Dashboard Gateway restart requires confirmation and post-command state verification.
- Profile/SOUL paths are validated against traversal.
- Provider credentials/API keys are not exposed by Management Center.
- WeChat outbound sends fail closed when the exact target cannot be verified.
- Keep Hermes Dashboard on localhost or behind trusted authentication/network controls.
