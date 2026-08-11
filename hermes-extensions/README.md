# Hermes Extensions

Standalone extensions for **NousResearch/hermes-agent**. This package does not depend on the OpenAkita runtime, APIs, agents, or databases.

Current package version: **0.4.5**.

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

For known group conversations, configure exact names with `WECHAT_DESKTOP_GROUP_CHATS` (comma separated) or the platform `extra.group_chats` value. Those conversations are routed to Hermes with `chat_type="group"`; other chats remain `dm` unless explicitly configured.

### Hermes Task Center

Task Center reads native per-profile Cron state, Cron execution history and native Hermes Kanban surfaces. Mutations use Hermes CLI operations.

Registered task tools: `task_center_overview`, `task_center_upcoming`, `task_center_create`, `task_center_update`, `task_center_action`, and `task_center_history`.

## v0.4.5 final runtime hardening

### Cross-process WeChat UI transaction lock

A single Windows WeChat window is shared by every Hermes process. v0.4.5 adds a hardened runtime facade that serializes UI Automation across tool calls, the Gateway and other plugin workers.

The exclusive transaction covers:

1. chat search/open;
2. exact target verification;
3. editor focus and paste;
4. final target verification;
5. Enter or dry-run cleanup;
6. duplicate-send state read/write.

The lock is re-entrant inside one call chain, uses a process-wide thread lock plus an OS file lock for other processes, and has a timeout. Lock timeout fails closed rather than allowing two workers to operate the desktop simultaneously.

### Better WeChat inbound identity and polling health

Inbound dedup no longer relies only on message text. The hardened desktop reader supplies a UI message identity derived from chat, sender, displayed time, row position and direction, so two legitimate identical customer messages can remain distinct. Outbound echo suppression intentionally keeps a short content-based fingerprint to prevent reply loops.

Gateway polling now tracks consecutive failures, last error and last successful poll. Repeated UIA failures move the adapter to `degraded`/`failed`, emit throttled warnings and use exponential backoff up to 30 seconds. Successful polling resets health to `healthy` and logs recovery.

### Fair upcoming-task visibility

Task Center v3 guarantees first-occurrence visibility before recurring jobs fill the remaining result budget. A high-frequency Cron job therefore cannot consume every result slot before another scheduled task gets its first occurrence represented (when the result limit is large enough for all first occurrences). Remaining recurring occurrences are merged and sorted globally by time.

Cron runtime status reads are also batched: overview opens each profile's `executions.db` once and queries the latest runs for all jobs in that profile, rather than opening SQLite once per Cron job.

### Canonical Management overview

Dashboard and Hermes tools now call one implementation in `management/overview.py`. Task counts, Project compatibility, capability state, upcoming work and partial errors cannot drift between the two surfaces.

## Existing v0.4 reliability protections

`install.ps1` detects the actual Hermes Python interpreter, stages and compiles the new plugin, backs up the existing extension, WeChat platform and `config.yaml`, atomically replaces the code, enables plugins, runs installed doctor checks, and restores files plus Hermes plugin configuration if the upgrade fails.

Capability probing is cached in-process for 45 seconds. `/capabilities?refresh=true` forces a re-probe. Dashboard dynamic modules are registered in `sys.modules` before execution for Python 3.11 dataclass compatibility. Pydantic v2 request models use `extra="forbid"`.

When `hermes project` is absent, Project reads return `supported: false`, mutations return a structured 409, and model-facing Project tools are not registered. Dashboard Project support can appear after an upgrade/capability refresh; Project tools require the Hermes/plugin process to restart or reload after that upgrade.

## Doctor modes

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

A first installation or Dashboard backend Python change should restart only `hermes dashboard`. Frontend-only updates can use Dashboard rescan. WeChat platform/runtime Python changes require restarting the relevant Hermes gateway, not reinstalling Hermes.

## Release package

The release workflow builds:

```text
hermes-extensions-v0.4.5.zip
hermes-extensions-v0.4.5.zip.sha256
```

The archive contains only the standalone Hermes extension tree, excludes OpenAkita application code and tests, and includes the pre-built `dashboard/dist/index.js` expected by Hermes Dashboard.

## Validation

CI covers Python compilation, Ruff, pytest, Dashboard JavaScript syntax, strict schemas/API bodies, Profile and Task regression tests, fair upcoming-task visibility, batched Cron-history reads, WeChat fail-closed send tests, cross-instance UI lock timeout, distinct inbound message identity, polling health/backoff, group-chat classification, capability cache/invalid-binary checks, Project-tool conditional registration, real Windows execution of `install.ps1`, installed doctor checks, failed-upgrade rollback of plugin files and `config.yaml`, and release ZIP isolation/SHA256 generation.

A real WeChat acceptance test still requires native Windows with a logged-in WeChat client. CI cannot substitute for device-level UI Automation testing.

## Security notes

- Default and active Profiles are protected from deletion.
- Autonomous Agent tools do not expose Profile deletion or Gateway restart.
- Human Dashboard Gateway restart requires confirmation and post-command state verification.
- Profile/SOUL paths are validated against traversal.
- Provider credentials/API keys are not exposed by Management Center.
- WeChat outbound sends fail closed when exact target verification or the cross-process UI lock cannot be obtained.
- Keep Hermes Dashboard on localhost or behind trusted authentication/network controls.
