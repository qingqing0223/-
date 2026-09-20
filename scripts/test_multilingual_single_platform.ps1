param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","toutiao","zhihu")]
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

Write-Host "Running bounded multilingual smoke test" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "Profile: config\monitoring.multilingual.windows.json" -ForegroundColor Cyan
Write-Host "Only verified keyword-pack entries are searched automatically." -ForegroundColor Yellow
Write-Host "The result JSON will include language_counts and minority_language_records." -ForegroundColor Yellow

python .\run_single_platform.py `
  --platform $Platform `
  --config .\config\monitoring.multilingual.windows.json `
  --once

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "PASS criteria:" -ForegroundColor Cyan
Write-Host "  crawler return_code = 0" -ForegroundColor Green
Write-Host "  classified_records > 0" -ForegroundColor Green
Write-Host "  dashboard_push.ok = true" -ForegroundColor Green
Write-Host "  language_counts is present" -ForegroundColor Green
Write-Host "Minority-language hits depend on what the platform actually returns for the verified terms." -ForegroundColor Yellow
