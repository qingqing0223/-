param(
    [string]$Config = ".\config\monitoring.ks-test.json"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

if (-not (Test-Path $Config)) {
    Write-Host "ERROR: Kuaishou test config not found: $Config" -ForegroundColor Red
    exit 2
}

Write-Host "=== Kuaishou local acceptance recheck ===" -ForegroundColor Cyan
Write-Host "This command does NOT crawl Kuaishou again." -ForegroundColor Yellow
Write-Host "It reprocesses the latest raw JSONL with the current normalizer/classifier-fallback code." -ForegroundColor Yellow
Write-Host "Classifier/API outages must not discard collected content/comments." -ForegroundColor Yellow
Write-Host ""

Write-Host "[1/2] Reprocessing latest Kuaishou raw JSONL..." -ForegroundColor Cyan
python .\scripts\reprocess_kuaishou_latest_raw.py --config $Config
$reprocessCode = $LASTEXITCODE
if ($reprocessCode -ne 0) {
    Write-Host "ERROR: Kuaishou raw reprocessing did not pass. Send the complete output to the coordinator." -ForegroundColor Red
    exit $reprocessCode
}

Write-Host ""
Write-Host "[2/2] Inspecting raw + classified PPT acceptance fields..." -ForegroundColor Cyan
python .\scripts\inspect_kuaishou_acceptance.py --config $Config
$inspectCode = $LASTEXITCODE

Write-Host ""
if ($inspectCode -eq 0) {
    Write-Host "Kuaishou local acceptance data is readable. Review first-level comments, nested replies, parent integrity, source types and public IP-region coverage above." -ForegroundColor Green
} else {
    Write-Host "Kuaishou still has one or more acceptance gaps. Send the complete JSON output above; do not recrawl yet." -ForegroundColor Yellow
}

exit $inspectCode
