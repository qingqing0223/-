param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","toutiao","zhihu")]
    [string]$Platform,

    [string]$Config = ".\config\monitoring.local.json"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

Write-Host "=== Attitude classifier recovery ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host ""
Write-Host "[1/2] Checking external classifier service..." -ForegroundColor Cyan
python .\scripts\check_classifier_service.py
$healthCode = $LASTEXITCODE
if ($healthCode -ne 0) {
    Write-Host "Classifier is still unavailable. No classified data file will be rewritten." -ForegroundColor Yellow
    Write-Host "Collection can continue in degraded mode. Fix the provider account/quota/network issue first." -ForegroundColor Yellow
    exit $healthCode
}

Write-Host ""
Write-Host "[2/2] Backfilling degraded rows without recrawling..." -ForegroundColor Cyan
python .\scripts\backfill_degraded_attitude.py --platform $Platform --config $Config
exit $LASTEXITCODE
