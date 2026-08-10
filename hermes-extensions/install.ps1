$ErrorActionPreference = "Stop"

$Source = Split-Path -Parent $MyInvocation.MyCommand.Path
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $HOME ".hermes" }
$Target = Join-Path $HermesHome "plugins\hermes-extensions"

Write-Host "Installing Hermes Extensions to $Target"
New-Item -ItemType Directory -Force -Path $Target | Out-Null

Get-ChildItem -LiteralPath $Source -Force | Where-Object {
    $_.Name -notin @(".git", "__pycache__", ".pytest_cache")
} | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $Target -Recurse -Force
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
    try {
        & hermes plugins enable hermes-extensions
    } catch {
        Write-Warning "Plugin copied, but automatic enable failed: $($_.Exception.Message)"
    }
}

Write-Host "Hermes Extensions installed. Restart Hermes/gateway and restart 'hermes dashboard' so plugin API routes are mounted."
