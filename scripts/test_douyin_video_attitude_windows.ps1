$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

if (-not $env:DASHSCOPE_API_KEY) {
    Write-Host "ERROR: DASHSCOPE_API_KEY is not set." -ForegroundColor Red
    exit 1
}

Write-Host "[1/2] Checking Suqi dashboard backend..." -ForegroundColor Cyan
python .\scripts\check_suqi_dashboard.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[2/2] Running one-shot Douyin video-attitude test..." -ForegroundColor Cyan
Write-Host "If Douyin shows verification or soft-empty results, stop here and do not start continuous polling yet." -ForegroundColor Yellow
python .\run_monitor.py --config .\config\monitoring.douyin.attitude.smoke.windows.json --once
exit $LASTEXITCODE
