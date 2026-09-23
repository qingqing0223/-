param(
    [string]$Config = ".\config\monitoring.local.json",
    [string]$VideoId = "3x9yw95ybvv3n3q"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

if (-not (Test-Path $Config)) {
    Write-Host "ERROR: config not found: $Config" -ForegroundColor Red
    exit 2
}

$resolvedConfig = (Resolve-Path $Config).Path
$cfg = Get-Content $resolvedConfig -Raw -Encoding UTF8 | ConvertFrom-Json
$MediaCrawlerRoot = [string]$cfg.media_crawler_root
if (-not $MediaCrawlerRoot -or -not (Test-Path (Join-Path $MediaCrawlerRoot "main.py"))) {
    Write-Host "ERROR: invalid media_crawler_root: $MediaCrawlerRoot" -ForegroundColor Red
    exit 3
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$parent = Split-Path ([string]$cfg.data_root) -Parent
$testRoot = Join-Path $parent ("ks_known_nested_acceptance_" + $timestamp)
New-Item -ItemType Directory -Path $testRoot -Force | Out-Null

Write-Host ""
Write-Host "=== Kuaishou known nested-reply acceptance ===" -ForegroundColor Cyan
Write-Host "VideoId: $VideoId" -ForegroundColor Cyan
Write-Host "Output:  $testRoot" -ForegroundColor Cyan
Write-Host ""

$patches = @(
    "patch_kuaishou_realtime_search.py",
    "patch_kuaishou_startup_resilience.py",
    "patch_kuaishou_login_resilience.py",
    "patch_kuaishou_comment_regions.py",
    "patch_kuaishou_comment_hierarchy.py",
    "patch_kuaishou_engagement_fields.py",
    "patch_kuaishou_creator_trial_safety.py",
    "patch_kuaishou_public_metrics.py"
)
foreach ($patch in $patches) {
    python (Join-Path ".\scripts" $patch) --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$oldPublicMetrics = $env:KUAISHOU_PUBLIC_METRICS
$env:KUAISHOU_PUBLIC_METRICS = "1"
$oldErrorActionPreference = $ErrorActionPreference
$rc = 1
try {
    Push-Location $MediaCrawlerRoot
    try {
        $ErrorActionPreference = "Continue"
        & uv run main.py --platform ks --lt qrcode --type detail --specified_id $VideoId --max_concurrency_num 1 --get_comment yes --get_sub_comment yes --save_data_option jsonl --save_data_path $testRoot --max_comments_count_singlenotes 200
        $rc = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
        Pop-Location
    }
} finally {
    $env:KUAISHOU_PUBLIC_METRICS = $oldPublicMetrics
}

if ($rc -ne 0) {
    Write-Host "KUAISHOU KNOWN NESTED CRAWL FAILED. rc=$rc" -ForegroundColor Red
    exit $rc
}

python .\scripts\inspect_kuaishou_known_nested.py --data-dir $testRoot --video-id $VideoId
$inspectCode = $LASTEXITCODE
if ($inspectCode -ne 0) {
    Write-Host "KUAISHOU KNOWN NESTED ACCEPTANCE FAILED." -ForegroundColor Red
    exit $inspectCode
}

Write-Host ""
Write-Host "KUAISHOU KNOWN NESTED ACCEPTANCE PASSED." -ForegroundColor Green
Write-Host "Verified: positive video comment total + first-level comments + nested replies + parent/root linkage." -ForegroundColor Green
exit 0
