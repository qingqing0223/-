$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

if (-not $env:DASHSCOPE_API_KEY) {
    Write-Host "ERROR: DASHSCOPE_API_KEY is not set." -ForegroundColor Red
    Write-Host 'Set it in this PowerShell window first: $env:DASHSCOPE_API_KEY="YOUR_NEW_KEY"' -ForegroundColor Yellow
    exit 1
}

Write-Host "[1/2] Checking Suqi dashboard backend..." -ForegroundColor Cyan
python .\scripts\check_suqi_dashboard.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[2/2] Running one-platform, one-keyword end-to-end smoke test..." -ForegroundColor Cyan
python .\run_monitor.py --config .\config\monitoring.smoke.windows.json --once
exit $LASTEXITCODE
