param(
    [switch]$RunTests
)

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

Write-Host "Applying one-time local Suqi integration patches..." -ForegroundColor Cyan

python .\scripts\patch_suqi_region_upsert.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python .\scripts\patch_suqi_minority_language_panel.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python .\scripts\patch_suqi_separate_platforms.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($RunTests) {
    Write-Host "Running language detector unit tests..." -ForegroundColor Cyan
    python -m unittest tests.test_language_detector -v
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "Running platform normalizer unit tests..." -ForegroundColor Cyan
    python -m unittest tests.test_platform_normalizer -v
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host ""
Write-Host "Local integration setup completed." -ForegroundColor Green
Write-Host "If Suqi server.py is currently running, restart it so backend patches take effect." -ForegroundColor Yellow
Write-Host "After restart, hard-refresh the browser (Ctrl+F5)." -ForegroundColor Yellow
Write-Host "Formal preheat deployment still needs a clean current-task baseline; this setup does not delete historical data." -ForegroundColor Yellow
