param(
    [string]$BaseConfig = ".\config\monitoring.local.json",
    [string]$MediaCrawlerRoot = ""
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

$builderArgs = @(
    ".\scripts\build_bilibili_acceptance_config.py",
    "--base", $resolvedBase,
    "--output", $TestConfig
)
if ($MediaCrawlerRoot) {
    $builderArgs += @("--media-crawler-root", $MediaCrawlerRoot)
}
python @builderArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$cfg = Get-Content $TestConfig -Raw -Encoding UTF8 | ConvertFrom-Json
$EffectiveMediaCrawlerRoot = [string]$cfg.media_crawler_root
if (-not $EffectiveMediaCrawlerRoot -or -not (Test-Path (Join-Path $EffectiveMediaCrawlerRoot "main.py"))) {
    Write-Host "ERROR: invalid media_crawler_root: $EffectiveMediaCrawlerRoot" -ForegroundColor Red
    exit 3
}

$patches = @(
    "patch_bilibili_login_resilience.py",
    "patch_bilibili_data_fields.py",
    "patch_bilibili_comment_detail.py",
    "patch_bilibili_network_resilience.py",
    "patch_bilibili_realtime_comment_bounds.py",
    "patch_bilibili_realtime_comment_order.py",
    "patch_bilibili_realtime_discovery_bound.py"
)

foreach ($patch in $patches) {
    Write-Host "Applying Bilibili patch: $patch" -ForegroundColor Cyan
    python (Join-Path ".\scripts" $patch) --root $EffectiveMediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    python (Join-Path ".\scripts" $patch) --root $EffectiveMediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "Applying public coarse-region persistence patch..." -ForegroundColor Cyan
python .\scripts\patch_mediacrawler_public_regions.py --root $EffectiveMediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python .\scripts\verify_mediacrawler_public_regions.py --root $EffectiveMediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "[1/4] Running preflight on isolated formal-scope config..." -ForegroundColor Cyan
python .\scripts\preflight.py --config $TestConfig --runtime-only --platform bili
if ($LASTEXITCODE -ne 0) {
    Write-Host "BILIBILI ACCEPTANCE BLOCKED: preflight failed." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "[2/4] Verifying reusable Bilibili login session..." -ForegroundColor Cyan
Write-Host "This step is outside the five-minute acceptance clock." -ForegroundColor Yellow
& .\scripts\bootstrap_bilibili_session_windows.ps1 -Config $TestConfig -MediaCrawlerRoot $EffectiveMediaCrawlerRoot
if ($LASTEXITCODE -ne 0) {
    Write-Host "BILIBILI ACCEPTANCE BLOCKED: login/session bootstrap failed." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "[3/4] Running one real bounded Bilibili cycle..." -ForegroundColor Cyan
python .\run_student_platform_final.py --platform bili --config $TestConfig --once
$runCode = $LASTEXITCODE
if ($runCode -ne 0) {
    Write-Host "BILIBILI REALTIME CYCLE FAILED. rc=$runCode" -ForegroundColor Red
    exit $runCode
}

Write-Host ""
Write-Host "[4/4] Inspecting realtime SLA, comments, hierarchy and public region..." -ForegroundColor Cyan
python .\scripts\inspect_bilibili_acceptance.py --config $TestConfig
$inspectCode = $LASTEXITCODE

Write-Host ""
Write-Host "Acceptance config: $TestConfig" -ForegroundColor DarkGray
Write-Host "Acceptance data:   $($cfg.data_root)_bili" -ForegroundColor DarkGray

if ($inspectCode -ne 0) {
    Write-Host "BILIBILI LOCAL ACCEPTANCE NOT YET COMPLETE." -ForegroundColor Red
    Write-Host "Keep this branch local/review-only; do not hand it to students yet." -ForegroundColor Yellow

    $platformRoot = ([string]$cfg.data_root) + "_bili"
    $statusPath = Join-Path $platformRoot "status\latest_status.json"
    if (Test-Path $statusPath) {
        try {
            $statusObj = Get-Content $statusPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $runObj = @($statusObj.platform_runs)[0]
            Write-Host ""
            Write-Host "=== Latest Bilibili stdout/stderr tail ===" -ForegroundColor Cyan
            foreach ($logPath in @([string]$runObj.stdout_log, [string]$runObj.stderr_log)) {
                if ($logPath -and (Test-Path $logPath)) {
                    Write-Host "--- $logPath ---" -ForegroundColor DarkGray
                    Get-Content $logPath -Tail 80 -Encoding UTF8
                }
            }
        } catch {
            Write-Host "Could not print latest Bilibili log tail: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }

    exit $inspectCode
}

Write-Host "BILIBILI LOCAL ACCEPTANCE PASSED." -ForegroundColor Green
Write-Host "Only after this result should the reviewed branch be handed to the student." -ForegroundColor Green
exit 0
