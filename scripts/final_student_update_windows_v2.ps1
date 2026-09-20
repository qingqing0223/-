param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","toutiao","zhihu")]
    [string]$Platform,

    [Parameter(Mandatory=$true)]
    [string]$NodeId,

    [string]$Config = ".\config\monitoring.local.json",
    [switch]$Start
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

Write-Host "=== FINAL student monitoring upgrade V2 ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "NodeId:   $NodeId" -ForegroundColor Cyan
Write-Host ""

# Reuse the already-stabilized deployment logic, but deliberately do not start
# the collector yet. We first patch/verify public region persistence and only
# then launch the monitor.
& .\scripts\final_student_update_windows.ps1 `
    -Platform $Platform `
    -NodeId $NodeId `
    -Config $Config
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: base final update failed; public-region patch was not attempted." -ForegroundColor Red
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
    Write-Host "ERROR: MediaCrawler public-region patch failed. Do not start monitoring." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "Verifying public-region patch..." -ForegroundColor Cyan
python .\scripts\verify_mediacrawler_public_regions.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: public-region verification failed. Do not start monitoring." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "FINAL V2 upgrade completed and verified." -ForegroundColor Green
Write-Host "Public-region policy: only coarse platform-displayed IP-location labels are retained; real IPs and precise locations are rejected." -ForegroundColor Yellow
Write-Host "Old JSONL created before this patch cannot gain region labels if the old collector never persisted them." -ForegroundColor Yellow
Write-Host "New collection cycles can populate regions/content_regions/comment_regions when the platform exposes a public region label." -ForegroundColor Yellow

if ($Start) {
    Write-Host "Starting final V2 monitor now..." -ForegroundColor Green
    & .\scripts\start_student_platform_windows.ps1 `
        -Platform $Platform `
        -NodeId $NodeId `
        -Config $Config `
        -PushGithub
    exit $LASTEXITCODE
}

Write-Host "Start command:" -ForegroundColor Cyan
Write-Host ".\scripts\start_student_platform_windows.ps1 -Platform $Platform -NodeId $NodeId -Config $Config -PushGithub" -ForegroundColor Green
