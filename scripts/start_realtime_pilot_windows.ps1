$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

if (-not $env:DASHSCOPE_API_KEY) {
    Write-Host "ERROR: DASHSCOPE_API_KEY is not set." -ForegroundColor Red
    Write-Host 'Set it in this PowerShell window first: $env:DASHSCOPE_API_KEY="YOUR_KEY"' -ForegroundColor Yellow
    exit 1
}

Write-Host "[1/2] Checking Suqi dashboard backend..." -ForegroundColor Cyan
python .\scripts\check_suqi_dashboard.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[2/2] Starting safe 5-minute realtime pilot (XHS only)..." -ForegroundColor Cyan
Write-Host "Douyin continuous polling stays disabled until its one-shot video-attitude test passes." -ForegroundColor Yellow
Write-Host "Press Ctrl+C to stop. Keep this PowerShell window open." -ForegroundColor Yellow
python .\run_monitor.py --config .\config\monitoring.realtime.pilot.windows.json
