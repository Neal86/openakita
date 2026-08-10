$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest

function Test-HermesCapability {
    param([string]$HermesExe, [string]$Command)
    try {
        $output = & $HermesExe $Command --help 2>&1 | Out-String
        if ($output -match "invalid choice|no such command|unknown command") { return $false }
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $HOME ".hermes" }
$Hermes = Get-Command hermes -ErrorAction SilentlyContinue
$Report = [ordered]@{
    hermes_on_path = [bool]$Hermes
    hermes_home = $HermesHome
    plugin_manifest = Test-Path (Join-Path $HermesHome "plugins\hermes-extensions\plugin.yaml")
    dashboard_manifest = Test-Path (Join-Path $HermesHome "plugins\hermes-extensions\dashboard\manifest.json")
    dashboard_bundle = Test-Path (Join-Path $HermesHome "plugins\hermes-extensions\dashboard\dist\index.js")
    dashboard_api = Test-Path (Join-Path $HermesHome "plugins\hermes-extensions\dashboard\compat_api.py")
    wechat_platform = Test-Path (Join-Path $HermesHome "plugins\platforms\wechat-desktop\plugin.yaml")
}

if ($Hermes) {
    foreach ($name in @("plugins", "dashboard", "profile", "project", "cron", "kanban")) {
        $Report["capability_$name"] = Test-HermesCapability -HermesExe $Hermes.Source -Command $name
    }
    try {
        $version = & $Hermes.Source --version 2>&1 | Out-String
        $Report["version"] = $version.Trim()
    } catch { $Report["version"] = "unknown" }
    try {
        $pluginList = & $Hermes.Source plugins list --plain --no-bundled 2>&1 | Out-String
        $Report["plugin_detected"] = $pluginList -match "hermes-extensions"
        $Report["wechat_plugin_detected"] = $pluginList -match "wechat-desktop"
    } catch {
        $Report["plugin_detected"] = $false
        $Report["wechat_plugin_detected"] = $false
    }
    try {
        $dashboard = & $Hermes.Source dashboard --status 2>&1 | Out-String
        $Report["dashboard_running"] = $dashboard -notmatch "No hermes dashboard processes running"
    } catch { $Report["dashboard_running"] = $false }
}

Write-Host "Hermes Extensions compatibility report"
Write-Host "-------------------------------------"
$Report.GetEnumerator() | ForEach-Object { Write-Host ("{0,-28} {1}" -f $_.Key, $_.Value) }

if ($Report.Contains("capability_project") -and -not $Report.capability_project) {
    Write-Host ""
    Write-Warning "Native Projects are unavailable in this Hermes build. This is supported: Agents, Tasks, Dashboard and WeChat still work."
}

$required = @("plugin_manifest", "dashboard_manifest", "dashboard_bundle", "dashboard_api", "wechat_platform")
$missing = @($required | Where-Object { -not $Report[$_] })
if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Warning ("Missing installed components: " + ($missing -join ", "))
    exit 2
}

Write-Host ""
Write-Host "Installed package structure looks valid."
exit 0
