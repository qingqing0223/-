$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

if (-not $env:DASHSCOPE_API_KEY) {
    Write-Host "ERROR: DASHSCOPE_API_KEY is not set." -ForegroundColor Red
    exit 1
}

Write-Host "[1/2] Checking Suqi dashboard backend..." -ForegroundColor Cyan
python .\scripts\check_suqi_dashboard.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[2/2] Starting 5-minute realtime loop: XHS + Douyin..." -ForegroundColor Cyan
Write-Host "Douyin should only be enabled after the one-shot attitude test passes without CAPTCHA/soft-empty." -ForegroundColor Yellow
Write-Host "Press Ctrl+C to stop. Keep this PowerShell window open." -ForegroundColor Yellow
python .\run_monitor.py --config .\config\monitoring.realtime.xhs_dy.windows.json
