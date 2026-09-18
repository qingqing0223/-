param(
    [string]$Config = ".\config\monitoring.local.json",
    [int]$MaxVideos = 0,
    [int]$MaxCommentsPerVideo = 1000
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

Write-Host "=== Douyin historical comment public-region backfill ===" -ForegroundColor Cyan
Write-Host "This enriches EXISTING classified comments only; it does not add a second historical corpus." -ForegroundColor Yellow
Write-Host "Stop the active Douyin collector first, but the GitHub sync window may remain open." -ForegroundColor Yellow
Write-Host ""

# Avoid two Douyin crawler processes sharing the same browser/profile.
try {
    $running = Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.CommandLine -and
        ($_.CommandLine -match "run_single_platform.py|run_student_platform_final.py") -and
        ($_.CommandLine -match "--platform\s+dy(?:\s|$)")
    }
    if ($running) {
        Write-Host "ERROR: a Douyin collector is still running." -ForegroundColor Red
        $running | Select-Object ProcessId, Name, CommandLine | Format-List
        Write-Host "Stop only the Douyin collector/watchdog, then rerun this backfill." -ForegroundColor Yellow
        exit 3
    }
} catch {
    Write-Host "Warning: process check unavailable; continuing carefully." -ForegroundColor Yellow
}

Write-Host "[1/5] Applying public-region persistence..." -ForegroundColor Cyan
python .\scripts\patch_mediacrawler_public_regions.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[2/5] Applying Douyin startup resilience..." -ForegroundColor Cyan
python .\scripts\patch_douyin_startup_resilience.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[3/5] Applying Douyin comment request profile v2..." -ForegroundColor Cyan
python .\scripts\patch_douyin_comment_request_profile.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[4/5] Applying Douyin parent/root hierarchy..." -ForegroundColor Cyan
python .\scripts\patch_douyin_comment_hierarchy.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[5/5] Re-fetching only videos referenced by existing comments and merging public regions..." -ForegroundColor Cyan
$argsList = @(
    ".\scripts\backfill_douyin_comment_regions.py",
    "--config", $Config,
    "--max-comments-per-video", $MaxCommentsPerVideo
)
if ($MaxVideos -gt 0) {
    $argsList += @("--max-videos", $MaxVideos)
}
python @argsList
exit $LASTEXITCODE
