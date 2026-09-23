param(
    [string]$BaseConfig = ".\config\monitoring.local.json"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

if (-not (Test-Path $BaseConfig)) {
    Write-Host "ERROR: base config not found: $BaseConfig" -ForegroundColor Red
    exit 2
}

$resolvedBase = (Resolve-Path $BaseConfig).Path
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$TestConfig = Join-Path $RepoRoot ("config\monitoring.bili-acceptance-" + $stamp + ".json")

Write-Host "=== Bilibili local realtime acceptance ===" -ForegroundColor Cyan
Write-Host "Branch code is tested locally before any student handoff." -ForegroundColor Yellow
Write-Host ""

python .\scripts\build_bilibili_acceptance_config.py --base $resolvedBase --output $TestConfig
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$cfg = Get-Content $TestConfig -Raw -Encoding UTF8 | ConvertFrom-Json
$MediaCrawlerRoot = [string]$cfg.media_crawler_root
if (-not $MediaCrawlerRoot -or -not (Test-Path (Join-Path $MediaCrawlerRoot "main.py"))) {
    Write-Host "ERROR: invalid media_crawler_root: $MediaCrawlerRoot" -ForegroundColor Red
    exit 3
}

$patches = @(
    "patch_bilibili_login_resilience.py",
    "patch_bilibili_comment_detail.py",
    "patch_bilibili_network_resilience.py",
    "patch_bilibili_realtime_comment_bounds.py",
    "patch_bilibili_realtime_comment_order.py",
    "patch_bilibili_realtime_discovery_bound.py"
)

foreach ($patch in $patches) {
    Write-Host "Applying Bilibili patch: $patch" -ForegroundColor Cyan
    python (Join-Path ".\scripts" $patch) --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    python (Join-Path ".\scripts" $patch) --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host ""
Write-Host "[1/3] Running preflight on isolated formal-scope config..." -ForegroundColor Cyan
python .\scripts\preflight.py --config $TestConfig
if ($LASTEXITCODE -ne 0) {
    Write-Host "BILIBILI ACCEPTANCE BLOCKED: preflight failed." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "[2/3] Running one real bounded Bilibili cycle..." -ForegroundColor Cyan
python .\run_student_platform_final.py --platform bili --config $TestConfig --once
$runCode = $LASTEXITCODE
if ($runCode -ne 0) {
    Write-Host "BILIBILI REALTIME CYCLE FAILED. rc=$runCode" -ForegroundColor Red
    exit $runCode
}

Write-Host ""
Write-Host "[3/3] Inspecting realtime SLA, comments, hierarchy and public region..." -ForegroundColor Cyan
python .\scripts\inspect_bilibili_acceptance.py --config $TestConfig
$inspectCode = $LASTEXITCODE

Write-Host ""
Write-Host "Acceptance config: $TestConfig" -ForegroundColor DarkGray
Write-Host "Acceptance data:   $($cfg.data_root)_bili" -ForegroundColor DarkGray

if ($inspectCode -ne 0) {
    Write-Host "BILIBILI LOCAL ACCEPTANCE NOT YET COMPLETE." -ForegroundColor Red
    Write-Host "Keep this branch local/review-only; do not hand it to students yet." -ForegroundColor Yellow
    exit $inspectCode
}

Write-Host "BILIBILI LOCAL ACCEPTANCE PASSED." -ForegroundColor Green
Write-Host "Only after this result should the reviewed branch be handed to the student." -ForegroundColor Green
exit 0
