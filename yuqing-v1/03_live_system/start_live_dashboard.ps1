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

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    $python = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $python) {
    throw "Python was not found. Install Python 3 and make sure python.exe is on PATH."
}

$pythonCommand = $python.Source
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
