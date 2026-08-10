$ErrorActionPreference = "Stop"

$Source = Split-Path -Parent $MyInvocation.MyCommand.Path
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $HOME ".hermes" }
$PluginsRoot = Join-Path $HermesHome "plugins"
$Target = Join-Path $PluginsRoot "hermes-extensions"
$PlatformTarget = Join-Path $PluginsRoot "platforms\wechat-desktop"

Write-Host "Installing Hermes Extensions to $Target"
New-Item -ItemType Directory -Force -Path $Target | Out-Null

Get-ChildItem -LiteralPath $Source -Force | Where-Object {
    $_.Name -notin @(".git", "__pycache__", ".pytest_cache", "platforms")
} | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $Target -Recurse -Force
}

Write-Host "Installing WeChat Desktop gateway platform to $PlatformTarget"
New-Item -ItemType Directory -Force -Path $PlatformTarget | Out-Null
Get-ChildItem -LiteralPath (Join-Path $Source "platforms\wechat-desktop") -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $PlatformTarget -Recurse -Force
}

$PythonCandidates = @(
    (Join-Path $env:LOCALAPPDATA "hermes\.venv\Scripts\python.exe"),
    (Join-Path $HermesHome "hermes-agent\.venv\Scripts\python.exe"),
    (Join-Path $HermesHome ".venv\Scripts\python.exe")
) | Where-Object { $_ -and (Test-Path $_) }

if ($PythonCandidates.Count -gt 0) {
    $HermesPython = $PythonCandidates[0]
    Write-Host "Installing Windows UI Automation dependencies with $HermesPython"
    & $HermesPython -m pip install -r (Join-Path $Target "requirements-windows.txt")
} else {
    Write-Warning "Hermes managed Python was not found automatically. Install requirements-windows.txt into the Python environment that runs Hermes."
}

$HermesCommand = Get-Command hermes -ErrorAction SilentlyContinue
if ($HermesCommand) {
    foreach ($PluginName in @("hermes-extensions", "wechat-desktop")) {
        try {
            & hermes plugins enable $PluginName
        } catch {
            Write-Warning "Plugin '$PluginName' was copied, but automatic enable failed: $($_.Exception.Message)"
        }
    }
}

Write-Host "Hermes Extensions installed."
Write-Host "For continuous WeChat -> Hermes gateway messages, enable gateway.platforms.wechat_desktop in Hermes config or set WECHAT_DESKTOP_AUTO_ENABLE=1."
Write-Host "Restart Hermes/gateway and restart 'hermes dashboard' so plugin API routes are mounted."
