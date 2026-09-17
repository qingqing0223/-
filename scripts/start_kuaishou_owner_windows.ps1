param(
    [string]$NodeId = "ks-main",
    [string]$Config = ".\config\monitoring.local.json"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

if (-not (Test-Path $Config)) {
    Write-Host "ERROR: config not found: $Config" -ForegroundColor Red
    exit 2
}

$cfg = Get-Content $Config -Raw -Encoding UTF8 | ConvertFrom-Json
$MediaCrawlerRoot = [string]$cfg.media_crawler_root
if (-not $MediaCrawlerRoot) { $MediaCrawlerRoot = "E:\MediaCrawler_clean" }

Write-Host "=== Kuaishou owner five-minute monitoring ===" -ForegroundColor Cyan
Write-Host "NodeId:   $NodeId" -ForegroundColor Cyan
Write-Host "Config:   $Config" -ForegroundColor Cyan
Write-Host "Cadence:  target 300 seconds start-to-start when a cycle finishes within target" -ForegroundColor Green
Write-Host "Public result sync: ON through the shared node launcher" -ForegroundColor Green
Write-Host "Full raw JSONL: retained locally; no separate private GitHub archive is required." -ForegroundColor Green
Write-Host ""

Write-Host "Applying/verifying Kuaishou comment public-region restoration..." -ForegroundColor Cyan
python .\scripts\patch_kuaishou_comment_regions.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Kuaishou comment-region restoration patch failed. Monitoring will not start with a partial patch." -ForegroundColor Red
    exit $LASTEXITCODE
}
python .\scripts\patch_kuaishou_comment_regions.py --root $MediaCrawlerRoot --check
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Kuaishou comment-region restoration verification failed." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "Attitude-classifier API failure does not stop collection; affected records remain preserved as unclassified/degraded." -ForegroundColor Yellow
Write-Host "Official login/captcha/security verification still requires normal manual completion." -ForegroundColor Yellow
Write-Host ""

& .\scripts\start_student_monitoring_final_windows.ps1 `
    -Platform ks `
    -NodeId $NodeId `
    -Config $Config

exit $LASTEXITCODE
