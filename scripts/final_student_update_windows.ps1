param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","tieba","zhihu")]
    [string]$Platform,

    [Parameter(Mandatory=$true)]
    [string]$NodeId,

    [string]$Config = ".\config\monitoring.local.json",
    [switch]$Start
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

Write-Host "=== FINAL student monitoring upgrade (frozen region-aware build) ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "NodeId:   $NodeId" -ForegroundColor Cyan
Write-Host ""

# Run the already-stabilized deployment/update logic first, but do not start the
# collector yet. Public-region persistence must be patched and verified before
# any new raw JSONL is created.
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

Write-Host ""
Write-Host "FINAL frozen build completed and verified." -ForegroundColor Green
Write-Host "Region collection policy:" -ForegroundColor Cyan
Write-Host "  - only platform-displayed coarse IP-location labels are retained" -ForegroundColor Yellow
Write-Host "  - real IP addresses and precise locations are rejected" -ForegroundColor Yellow
Write-Host "  - GitHub continues to receive aggregate region counts, not raw user-level region rows" -ForegroundColor Yellow
Write-Host "  - old JSONL created before this patch cannot be repaired if the old collector never persisted region labels" -ForegroundColor Yellow
Write-Host ""

if ($Start) {
    Write-Host "Starting final region-aware monitor now..." -ForegroundColor Green
    & .\scripts\start_student_platform_windows.ps1 `
        -Platform $Platform `
        -NodeId $NodeId `
        -Config $Config `
        -PushGithub
    exit $LASTEXITCODE
}

Write-Host "Start command:" -ForegroundColor Cyan
Write-Host ".\scripts\start_student_platform_windows.ps1 -Platform $Platform -NodeId $NodeId -Config $Config -PushGithub" -ForegroundColor Green
