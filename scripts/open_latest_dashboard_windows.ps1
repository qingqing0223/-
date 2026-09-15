$ErrorActionPreference = "Stop"

$callerLocation = Get-Location
$repo = "E:\Real-time-situation-map"
$live = Join-Path $repo "yuqing-v1\03_live_system"
$url = "http://127.0.0.1:8765/"
$health = "http://127.0.0.1:8765/api/health"

if (-not (Test-Path $repo)) {
    Write-Host "Dashboard repo not found: $repo" -ForegroundColor Red
    exit 1
}

try {
    Write-Host "Updating Suqi dashboard repo..." -ForegroundColor Cyan
    Set-Location $repo
    git pull

    $running = $false
    try {
        $r = Invoke-RestMethod $health -TimeoutSec 2
        if ($r.ok) { $running = $true }
    } catch {}

    if (-not $running) {
        Write-Host "Starting dashboard backend in a new PowerShell window..." -ForegroundColor Cyan
        $cmd = "Set-Location '$live'; python server.py --no-sim"
        Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd
        Start-Sleep -Seconds 4
    }

    Write-Host "Opening latest dashboard: $url" -ForegroundColor Green
    Start-Process $url
}
finally {
    Set-Location $callerLocation
}
