$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Source = Split-Path -Parent $MyInvocation.MyCommand.Path
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $HOME ".hermes" }
$PluginsRoot = Join-Path $HermesHome "plugins"
$Target = Join-Path $PluginsRoot "hermes-extensions"
$PlatformSource = Join-Path $Source "platforms\wechat-desktop"
$PlatformTarget = Join-Path $PluginsRoot "platforms\wechat-desktop"
$Requirements = Join-Path $Source "requirements-windows.txt"

foreach ($RequiredPath in @(
    (Join-Path $Source "plugin.yaml"),
    (Join-Path $Source "dashboard\manifest.json"),
    (Join-Path $Source "wechat\adapter.py"),
    (Join-Path $PlatformSource "plugin.yaml"),
    $Requirements
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Hermes Extensions package is incomplete: missing $RequiredPath"
    }
}

Write-Host "Hermes home: $HermesHome"
Write-Host "Installing Hermes Extensions to $Target"
New-Item -ItemType Directory -Force -Path $PluginsRoot | Out-Null

# Plugin runtime data lives under ~/.hermes/plugin-data, not in this code
# directory, so a clean replacement is safe and prevents stale upgrade files.
if (Test-Path -LiteralPath $Target) {
    Remove-Item -LiteralPath $Target -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $Target | Out-Null

Get-ChildItem -LiteralPath $Source -Force | Where-Object {
    $_.Name -notin @(".git", "__pycache__", ".pytest_cache", "platforms", "tests")
} | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $Target -Recurse -Force
}

Write-Host "Installing WeChat Desktop gateway platform to $PlatformTarget"
if (Test-Path -LiteralPath $PlatformTarget) {
    Remove-Item -LiteralPath $PlatformTarget -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $PlatformTarget | Out-Null
Get-ChildItem -LiteralPath $PlatformSource -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $PlatformTarget -Recurse -Force
}

$PythonCandidates = @(
    (Join-Path $env:LOCALAPPDATA "hermes\.venv\Scripts\python.exe"),
    (Join-Path $HermesHome "hermes-agent\.venv\Scripts\python.exe"),
    (Join-Path $HermesHome ".venv\Scripts\python.exe")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

$HermesPython = $null
if ($PythonCandidates.Count -gt 0) {
    $HermesPython = $PythonCandidates[0]
} else {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($PythonCommand) {
        $HermesPython = $PythonCommand.Source
    }
}

$InstalledDependencies = $false
if ($HermesPython) {
    Write-Host "Installing Windows UI Automation dependencies with $HermesPython"
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
        } else {
            throw
        }
    }
} else {
    Write-Warning "Python was not found automatically. Install requirements-windows.txt into the Python environment that runs Hermes."
}

$HermesCommand = Get-Command hermes -ErrorAction SilentlyContinue
if ($HermesCommand) {
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
    try {
        Write-Host "Installed Hermes plugins:"
        & $HermesCommand.Source plugins list
    } catch {
        Write-Warning "Unable to list Hermes plugins after install: $($_.Exception.Message)"
    }
} else {
    Write-Warning "The 'hermes' command is not on PATH. Files were installed but plugins could not be enabled automatically."
}

Write-Host "Hermes Extensions install complete."
Write-Host "Windows UI dependencies installed: $InstalledDependencies"
Write-Host "For continuous WeChat -> Hermes gateway messages, enable gateway.platforms.wechat_desktop in Hermes config or set WECHAT_DESKTOP_AUTO_ENABLE=1."
Write-Host "Restart Hermes/gateway. For the dashboard, restart 'hermes dashboard' or use its plugin rescan endpoint."
