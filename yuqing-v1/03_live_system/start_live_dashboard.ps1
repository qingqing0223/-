param(
    [int]$Port = 8765,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

$env:LIVE_PLATFORM_ENABLED = "1"
$env:LIVE_SIM_ENABLED = "0"
$env:LIVE_FILE_WATCH_ENABLED = "0"
$env:LIVE_PORT = "$Port"

$pythonCommand = $null
if ($env:LIVE_PYTHON -and (Test-Path -LiteralPath $env:LIVE_PYTHON)) {
    $pythonCommand = (Resolve-Path -LiteralPath $env:LIVE_PYTHON).Path
}
if (-not $pythonCommand) {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $pythonCommand = $python.Source
    }
}
if (-not $pythonCommand) {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $pythonCommand = $py.Source
    }
}
if (-not $pythonCommand) {
    $runtimeCandidates = @(
        (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"),
        (Join-Path $env:USERPROFILE ".codex\runtimes\python\python.exe")
    )
    $pythonCommand = $runtimeCandidates |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
}
if (-not $pythonCommand) {
    throw "Python was not found. Install Python 3, set LIVE_PYTHON, or add python.exe to PATH."
}
Write-Host "Starting real-time dashboard..."
Write-Host "Project: $ProjectDir"
Write-Host "URL:     http://127.0.0.1:$Port/"
Write-Host "Real platform collectors: ON"
Write-Host "Simulator: OFF"

$serverProcess = Start-Process `
    -FilePath $pythonCommand `
    -ArgumentList @("server.py") `
    -WorkingDirectory $ProjectDir `
    -PassThru `
    -NoNewWindow

$url = "http://127.0.0.1:$Port/"
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
            $ready = $true
            break
        }
    } catch {
        if ($serverProcess.HasExited) {
            throw "The dashboard server stopped during startup. Exit code: $($serverProcess.ExitCode)"
        }
    }
}

if (-not $ready) {
    if (-not $serverProcess.HasExited) {
        Stop-Process -Id $serverProcess.Id -Force
    }
    throw "Dashboard did not become ready within 15 seconds."
}

if (-not $NoBrowser) {
    Start-Process $url
}

Write-Host "Dashboard is ready: $url"
Write-Host "Close this PowerShell window to stop the dashboard."
Wait-Process -Id $serverProcess.Id
