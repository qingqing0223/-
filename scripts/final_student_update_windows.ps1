param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","tieba","zhihu")]
    [string]$Platform,

    [Parameter(Mandatory=$true)]
    [string]$NodeId,

    [string]$Config = ".\config\monitoring.local.json",
    [switch]$Start,
    [switch]$ArchiveRaw,
    [string]$RawArchiveRepo = $env:PROMOTION_RAW_ARCHIVE_REPO,
    [switch]$PrivateRepoConfirmed
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

Write-Host "=== FINAL student monitoring upgrade (five-minute realtime + region-aware build) ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "NodeId:   $NodeId" -ForegroundColor Cyan
Write-Host ""

& .\scripts\final_student_update_base_windows.ps1 `
    -Platform $Platform `
    -NodeId $NodeId `
    -Config $Config
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: base final update failed; monitor was not started." -ForegroundColor Red
    exit $LASTEXITCODE
}

if (-not (Test-Path $Config)) {
    Write-Host "ERROR: machine-local config not found after base update: $Config" -ForegroundColor Red
    exit 20
}

$cfgObj = Get-Content $Config -Raw -Encoding UTF8 | ConvertFrom-Json
$MediaCrawlerRoot = [string]$cfgObj.media_crawler_root
if (-not $MediaCrawlerRoot) {
    $MediaCrawlerRoot = "E:\MediaCrawler_clean"
}

Write-Host ""
Write-Host "Applying coarse public IP-region persistence patch..." -ForegroundColor Cyan
python .\scripts\patch_mediacrawler_public_regions.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: MediaCrawler public-region patch failed. Monitor will NOT start." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "Verifying public-region patch..." -ForegroundColor Cyan
python .\scripts\verify_mediacrawler_public_regions.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: public-region verification failed. Monitor will NOT start." -ForegroundColor Red
    exit $LASTEXITCODE
}

if ($Platform -eq "ks") {
    Write-Host "Applying Kuaishou public comment-region recovery patch..." -ForegroundColor Cyan
    python .\scripts\patch_kuaishou_comment_regions.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Kuaishou public comment-region patch failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    python .\scripts\patch_kuaishou_comment_regions.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Kuaishou public comment-region verification failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host "Applying Kuaishou comment-count + nested parent/root patch..." -ForegroundColor Cyan
    python .\scripts\patch_kuaishou_comment_hierarchy.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Kuaishou comment hierarchy patch failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    python .\scripts\patch_kuaishou_comment_hierarchy.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Kuaishou comment hierarchy verification failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Write-Host ""
Write-Host "FINAL build completed and verified." -ForegroundColor Green
Write-Host "Collection policy:" -ForegroundColor Cyan
Write-Host "  - one-time historical backfill is separate from the five-minute realtime loop" -ForegroundColor Yellow
Write-Host "  - realtime loop prioritizes new-content discovery every 300 seconds and queues deep comment crawling" -ForegroundColor Yellow
Write-Host "  - first-level + nested comments and parent/root links are retained when exposed" -ForegroundColor Yellow
Write-Host "  - Kuaishou persists video comment_count so comment-bearing videos enter the realtime detail queue" -ForegroundColor Yellow
Write-Host "  - only platform-displayed coarse IP-location labels are retained; real IP/precise location are rejected" -ForegroundColor Yellow
Write-Host "  - the public code repo receives aggregates + privacy-safe diagnostics only" -ForegroundColor Yellow
Write-Host "  - full raw JSONL can be synchronized separately to an access-controlled PRIVATE Git repository" -ForegroundColor Yellow
Write-Host ""
Write-Host "Before realtime monitoring, run one historical catch-up if this node has not done so:" -ForegroundColor Cyan
Write-Host ".\scripts\run_initial_backfill_windows.ps1 -Platform $Platform -Config $Config" -ForegroundColor Green
Write-Host ""

if ($Start) {
    Write-Host "Starting final five-minute realtime monitor now..." -ForegroundColor Green
    $args = @(
        "-Platform", $Platform,
        "-NodeId", $NodeId,
        "-Config", $Config,
        "-PushGithub"
    )
    if ($ArchiveRaw) {
        $args += @("-ArchiveRaw", "-RawArchiveRepo", $RawArchiveRepo)
        if ($PrivateRepoConfirmed) { $args += "-PrivateRepoConfirmed" }
    }
    & .\scripts\start_student_platform_windows.ps1 @args
    exit $LASTEXITCODE
}

Write-Host "Realtime start command:" -ForegroundColor Cyan
Write-Host ".\scripts\start_student_platform_windows.ps1 -Platform $Platform -NodeId $NodeId -Config $Config -PushGithub" -ForegroundColor Green

Write-Host ""
Write-Host "After at least one fresh collection cycle, verify public-region persistence with:" -ForegroundColor Cyan
Write-Host ".\scripts\check_public_region_acceptance_windows.ps1 -Platform $Platform -Config $Config" -ForegroundColor Green
if ($ArchiveRaw) {
    Write-Host "Realtime + private raw archive start command:" -ForegroundColor Cyan
    Write-Host ".\scripts\start_student_platform_windows.ps1 -Platform $Platform -NodeId $NodeId -Config $Config -PushGithub -ArchiveRaw -RawArchiveRepo '$RawArchiveRepo' -PrivateRepoConfirmed" -ForegroundColor Green
}
