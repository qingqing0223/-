param(
    [string]$NodeId = "ks-main",
    [string]$Config = ".\config\monitoring.local.json"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

Write-Host "=== Kuaishou owner five-minute monitoring ===" -ForegroundColor Cyan
Write-Host "NodeId:   $NodeId" -ForegroundColor Cyan
Write-Host "Config:   $Config" -ForegroundColor Cyan
Write-Host "Cadence:  target 300 seconds start-to-start when a cycle finishes within target" -ForegroundColor Green
Write-Host "Public summary sync: enabled through the shared node launcher" -ForegroundColor Green

$rawRepo = [string]$env:PROMOTION_RAW_ARCHIVE_REPO
$autoRaw = ([string]$env:PROMOTION_RAW_ARCHIVE_AUTO).ToLower() -in @("1", "true", "yes", "y")
$privateConfirmed = ([string]$env:PROMOTION_RAW_ARCHIVE_PRIVATE_CONFIRMED).ToLower() -in @("1", "true", "yes", "y")

if ($autoRaw -and $rawRepo -and $privateConfirmed -and (Test-Path (Join-Path $rawRepo ".git"))) {
    Write-Host "Private raw/GPT feed sync: ON -> $rawRepo" -ForegroundColor Green
} else {
    Write-Host "Private raw/GPT feed sync: OFF" -ForegroundColor Yellow
    Write-Host "Configure once with .\scripts\configure_private_raw_archive_windows.ps1 before formal monitoring if full raw JSONL should return to a private GitHub repo." -ForegroundColor Yellow
}

Write-Host "Attitude-classifier API failure does not stop collection; affected records remain preserved as unclassified/degraded." -ForegroundColor Yellow
Write-Host "Official login/captcha/security verification still requires normal manual completion." -ForegroundColor Yellow
Write-Host ""

& .\scripts\start_student_monitoring_final_windows.ps1 `
    -Platform ks `
    -NodeId $NodeId `
    -Config $Config

exit $LASTEXITCODE
