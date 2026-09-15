param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","wb","ks")]
    [string]$Platform
)

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

if (-not $env:DASHSCOPE_API_KEY) {
    Write-Host "ERROR: DASHSCOPE_API_KEY is not set." -ForegroundColor Red
    exit 1
}

Write-Host "Checking Suqi dashboard backend..." -ForegroundColor Cyan
python .\scripts\check_suqi_dashboard.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Starting one-platform 5-minute realtime monitor: $Platform" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop. Do not start another monitor for the same platform at the same time." -ForegroundColor Yellow
python .\run_single_platform.py --platform $Platform
