$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Source = Split-Path -Parent $MyInvocation.MyCommand.Path
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $HOME ".hermes" }
$PluginsRoot = Join-Path $HermesHome "plugins"
$Target = Join-Path $PluginsRoot "hermes-extensions"
$PlatformSource = Join-Path $Source "platforms\wechat-desktop"
$PlatformTarget = Join-Path $PluginsRoot "platforms\wechat-desktop"
$Requirements = Join-Path $Source "requirements-windows.txt"
$DashboardSource = Join-Path $Source "dashboard\src\index.js"

foreach ($RequiredPath in @(
    (Join-Path $Source "plugin.yaml"),
    (Join-Path $Source "dashboard\manifest.json"),
    (Join-Path $Source "dashboard\compat_api.py"),
    $DashboardSource,
    (Join-Path $Source "wechat\adapter.py"),
    (Join-Path $PlatformSource "plugin.yaml"),
    $Requirements
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Hermes Extensions package is incomplete: missing $RequiredPath"
    }
}

function Test-HermesCapability {
    param([string]$HermesExe, [string]$Command)
    try {
        $output = & $HermesExe $Command --help 2>&1 | Out-String
        if ($output -match "invalid choice|no such command|unknown command") { return $false }
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

$HermesCommand = Get-Command hermes -ErrorAction SilentlyContinue
$Capabilities = [ordered]@{
    hermes = [bool]$HermesCommand
    plugins = $false
    dashboard = $false
    profile = $false
    project = $false
    cron = $false
    kanban = $false
}
if ($HermesCommand) {
    foreach ($name in @("plugins", "dashboard", "profile", "project", "cron", "kanban")) {
        $Capabilities[$name] = Test-HermesCapability -HermesExe $HermesCommand.Source -Command $name
    }
}

Write-Host "Hermes home: $HermesHome"
Write-Host "Detected Hermes capabilities:"
$Capabilities.GetEnumerator() | ForEach-Object { Write-Host ("  {0,-10} {1}" -f $_.Key, $_.Value) }
if (-not $Capabilities.project) {
    Write-Warning "Native 'hermes project' is not available. Projects will be disabled; Agents, Tasks and WeChat remain available."
}

Write-Host "Installing Hermes Extensions to $Target"
New-Item -ItemType Directory -Force -Path $PluginsRoot | Out-Null
if (Test-Path -LiteralPath $Target) {
    Remove-Item -LiteralPath $Target -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $Target | Out-Null

Get-ChildItem -LiteralPath $Source -Force | Where-Object {
    $_.Name -notin @(".git", "__pycache__", ".pytest_cache", "platforms", "tests")
} | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $Target -Recurse -Force
}

# Hermes v0.16 dashboard plugins expect a pre-built single JS entry under dist/.
$TargetDashboardDist = Join-Path $Target "dashboard\dist"
New-Item -ItemType Directory -Force -Path $TargetDashboardDist | Out-Null
Copy-Item -LiteralPath $DashboardSource -Destination (Join-Path $TargetDashboardDist "index.js") -Force

Write-Host "Installing WeChat Desktop gateway platform to $PlatformTarget"
if (Test-Path -LiteralPath $PlatformTarget) {
    Remove-Item -LiteralPath $PlatformTarget -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $PlatformTarget | Out-Null
Get-ChildItem -LiteralPath $PlatformSource -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $PlatformTarget -Recurse -Force
}

$PythonCandidates = @(
    (Join-Path $env:LOCALAPPDATA "uv\tools\hermes-agent\Scripts\python.exe"),
    (Join-Path $env:LOCALAPPDATA "hermes\.venv\Scripts\python.exe"),
    (Join-Path $HermesHome "hermes-agent\.venv\Scripts\python.exe"),
    (Join-Path $HermesHome ".venv\Scripts\python.exe")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

$HermesPython = $null
if ($PythonCandidates.Count -gt 0) {
    $HermesPython = $PythonCandidates[0]
} else {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($PythonCommand) { $HermesPython = $PythonCommand.Source }
}

$InstalledDependencies = $false
if ($HermesPython) {
    Write-Host "Installing plugin dependencies with $HermesPython"
    try {
        & $HermesPython -m pip install -r (Join-Path $Target "requirements-windows.txt")
        if ($LASTEXITCODE -ne 0) { throw "pip exited with code $LASTEXITCODE" }
        $InstalledDependencies = $true
    } catch {
        $UvCommand = Get-Command uv -ErrorAction SilentlyContinue
        if ($UvCommand) {
            Write-Warning "pip install failed; retrying with uv. $($_.Exception.Message)"
            & $UvCommand.Source pip install --python $HermesPython -r (Join-Path $Target "requirements-windows.txt")
            if ($LASTEXITCODE -ne 0) { throw "uv pip install exited with code $LASTEXITCODE" }
            $InstalledDependencies = $true
        } else { throw }
    }
} else {
    Write-Warning "Python was not found automatically. Install requirements-windows.txt into the Python environment that runs Hermes."
}

if ($HermesCommand -and $Capabilities.plugins) {
    foreach ($PluginName in @("hermes-extensions", "wechat-desktop")) {
        try {
            & $HermesCommand.Source plugins enable $PluginName
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "Plugin '$PluginName' was copied but Hermes returned exit code $LASTEXITCODE while enabling it."
            }
        } catch {
            Write-Warning "Plugin '$PluginName' was copied, but automatic enable failed: $($_.Exception.Message)"
        }
    }
    Write-Host "Installed Hermes plugins:"
    try { & $HermesCommand.Source plugins list --plain --no-bundled } catch { & $HermesCommand.Source plugins list }
}

$DashboardRescanned = $false
if ($Capabilities.dashboard) {
    try {
        $status = & $HermesCommand.Source dashboard --status 2>&1 | Out-String
        if ($status -notmatch "No hermes dashboard processes running") {
            try {
                Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:9119/api/dashboard/plugins/rescan" -TimeoutSec 5 | Out-Null
                $DashboardRescanned = $true
                Write-Host "Dashboard plugin rescan completed."
            } catch {
                Write-Warning "Dashboard is running but plugin rescan failed: $($_.Exception.Message)"
            }
        }
    } catch {}
}

$InstalledChecks = [ordered]@{
    plugin_manifest = Test-Path -LiteralPath (Join-Path $Target "plugin.yaml")
    dashboard_manifest = Test-Path -LiteralPath (Join-Path $Target "dashboard\manifest.json")
    dashboard_bundle = Test-Path -LiteralPath (Join-Path $Target "dashboard\dist\index.js")
    dashboard_api = Test-Path -LiteralPath (Join-Path $Target "dashboard\compat_api.py")
    wechat_platform = Test-Path -LiteralPath (Join-Path $PlatformTarget "plugin.yaml")
}

Write-Host "Install verification:"
$InstalledChecks.GetEnumerator() | ForEach-Object { Write-Host ("  {0,-20} {1}" -f $_.Key, $_.Value) }
if ($InstalledChecks.Values -contains $false) {
    throw "Hermes Extensions installation verification failed."
}

Write-Host "Hermes Extensions v0.4.1 install complete."
Write-Host "Dependencies installed: $InstalledDependencies"
Write-Host "Dashboard hot rescan: $DashboardRescanned"
if (-not $Capabilities.project) {
    Write-Host "Projects: disabled for this Hermes build (no native 'hermes project'); they will auto-enable after a compatible Hermes upgrade."
}
Write-Host "Run '.\doctor.ps1' from the package, or '$Target\doctor.ps1', for a compatibility report."
Write-Host "If this is the first install or dashboard backend API changed, restart only 'hermes dashboard'."
Write-Host "For WeChat platform Python changes, restart the relevant Hermes gateway; the whole Hermes installation does not need reinstalling."
