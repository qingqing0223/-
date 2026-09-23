param(
    [string]$BaseConfig = ".\config\monitoring.ks-test.json"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

if (-not (Test-Path $BaseConfig)) {
    Write-Host "ERROR: base Kuaishou config not found: $BaseConfig" -ForegroundColor Red
    exit 2
}

$cfg = Get-Content $BaseConfig -Raw -Encoding UTF8 | ConvertFrom-Json
$MediaCrawlerRoot = [string]$cfg.media_crawler_root
if (-not $MediaCrawlerRoot) { $MediaCrawlerRoot = "E:\MediaCrawler_clean" }

Write-Host "=== Kuaishou five-minute realtime acceptance ===" -ForegroundColor Cyan
Write-Host "This is a single bounded REALTIME cycle, not historical full backfill." -ForegroundColor Yellow
Write-Host "Discovery is prioritized; comment detail work has a finite time budget." -ForegroundColor Yellow
Write-Host "Comment IP-region is now a strict acceptance item because Kuaishou publicly displays it." -ForegroundColor Yellow
Write-Host "Video likes, platform comment count, follower/following and comment likes are also strict live acceptance items." -ForegroundColor Yellow
Write-Host ""

Write-Host "Configuring Kuaishou browser lifecycle (self-launched CDP; no external 9222 dependency)..." -ForegroundColor Cyan
& .\scripts\enable_mediacrawler_cdp.ps1 -MediaCrawlerRoot $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }


Write-Host "Applying/verifying Kuaishou realtime discovery slice..." -ForegroundColor Cyan
python .\scripts\patch_kuaishou_realtime_search.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python .\scripts\patch_kuaishou_realtime_search.py --root $MediaCrawlerRoot --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Applying/verifying Kuaishou startup resilience patch..." -ForegroundColor Cyan
python .\scripts\patch_kuaishou_startup_resilience.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python .\scripts\patch_kuaishou_startup_resilience.py --root $MediaCrawlerRoot --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Applying/verifying Kuaishou session/login resilience patch..." -ForegroundColor Cyan
python .\scripts\patch_kuaishou_login_resilience.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python .\scripts\patch_kuaishou_login_resilience.py --root $MediaCrawlerRoot --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Applying/verifying current Kuaishou comment/hierarchy patch..." -ForegroundColor Cyan
python .\scripts\patch_kuaishou_comment_hierarchy.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python .\scripts\patch_kuaishou_comment_hierarchy.py --root $MediaCrawlerRoot --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Applying/verifying Kuaishou comment public-region restoration..." -ForegroundColor Cyan
python .\scripts\patch_kuaishou_comment_regions.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python .\scripts\patch_kuaishou_comment_regions.py --root $MediaCrawlerRoot --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Applying/verifying Kuaishou video/comment engagement persistence..." -ForegroundColor Cyan
python .\scripts\patch_kuaishou_engagement_fields.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python .\scripts\patch_kuaishou_engagement_fields.py --root $MediaCrawlerRoot --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Applying/verifying Kuaishou public follower/following/comment-like metrics..." -ForegroundColor Cyan
python .\scripts\patch_kuaishou_creator_trial_safety.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python .\scripts\patch_kuaishou_creator_trial_safety.py --root $MediaCrawlerRoot --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python .\scripts\patch_kuaishou_public_metrics.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python .\scripts\patch_kuaishou_public_metrics.py --root $MediaCrawlerRoot --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$env:KUAISHOU_PUBLIC_METRICS = "1"

function Set-ConfigProperty($obj, [string]$name, $value) {
    if ($obj.PSObject.Properties.Name -contains $name) {
        $obj.$name = $value
    } else {
        $obj | Add-Member -NotePropertyName $name -NotePropertyValue $value
    }
}

$stamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$driveRoot = "E:\MediaCrawlerData"
if ([string]$cfg.data_root) {
    try {
        $existing = [System.IO.Path]::GetPathRoot([string]$cfg.data_root)
        if ($existing) { $driveRoot = Join-Path $existing "MediaCrawlerData" }
    } catch {}
}
$testDataRoot = Join-Path $driveRoot ("{0}_ks_realtime_acceptance" -f $stamp)
$platformTestRoot = "$testDataRoot`_ks"

Set-ConfigProperty $cfg "data_root" $testDataRoot
Set-ConfigProperty $cfg "results_date" ""
Set-ConfigProperty $cfg "results_date_mode" "auto"
Set-ConfigProperty $cfg "realtime_mode" $true
Set-ConfigProperty $cfg "interval_seconds" 300
Set-ConfigProperty $cfg "realtime_discovery_max_notes_count" 30
Set-ConfigProperty $cfg "realtime_detail_max_items_per_cycle" 6
Set-ConfigProperty $cfg "realtime_detail_batch_size" 2
Set-ConfigProperty $cfg "realtime_comment_refresh_seconds" 300
Set-ConfigProperty $cfg "kuaishou_realtime_detail_budget_seconds" 120
Set-ConfigProperty $cfg "kuaishou_realtime_max_comments_per_video" 300
Set-ConfigProperty $cfg "kuaishou_realtime_detail_batch_size" 2
Set-ConfigProperty $cfg "get_comment" "yes"
Set-ConfigProperty $cfg "get_sub_comment" "yes"
Set-ConfigProperty $cfg "ingest_comments" $true
Set-ConfigProperty $cfg "max_concurrency_num" 1

$TestConfig = Join-Path $RepoRoot "config\monitoring.ks-realtime-test.json"
$json = $cfg | ConvertTo-Json -Depth 100
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($TestConfig, $json, $utf8NoBom)

Write-Host "Realtime test config: $TestConfig" -ForegroundColor Cyan
Write-Host "Realtime test data:   $platformTestRoot" -ForegroundColor Cyan
Write-Host ""
Write-Host "[0/4] Verifying reusable Kuaishou login session before the timed cycle..." -ForegroundColor Cyan
& .\scripts\bootstrap_kuaishou_session_windows.ps1 -Config $TestConfig
$bootstrapCode = $LASTEXITCODE
if ($bootstrapCode -ne 0) {
    Write-Host "Blocking gap: Kuaishou login/session is not verified. Timed acceptance will not start." -ForegroundColor Red
    exit $bootstrapCode
}
Write-Host ""

Write-Host "[1/4] Running one bounded realtime cycle..." -ForegroundColor Cyan
$started = Get-Date
python .\run_single_platform.py --platform ks --config $TestConfig --once
$runCode = $LASTEXITCODE
$elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
Write-Host "Wall-clock elapsed: $elapsed seconds" -ForegroundColor Cyan
if ($runCode -ne 0) {
    Write-Host "Collector returned non-zero. Acceptance inspection will still run because partial raw JSONL may be valid." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[2/4] Reprocessing the latest raw cycle, then inspecting comments + hierarchy acceptance..." -ForegroundColor Cyan
python .\scripts\reprocess_kuaishou_latest_raw.py --config $TestConfig
$reprocessCode = $LASTEXITCODE
if ($reprocessCode -ne 0) {
    Write-Host "Acceptance reprocess did not complete cleanly; inspector will use latest-raw structural fallback." -ForegroundColor Yellow
}
python .\scripts\inspect_kuaishou_acceptance.py --config $TestConfig
$inspectCode = $LASTEXITCODE

Write-Host ""
Write-Host "[3/4] Strictly verifying Kuaishou comment public IP-region restoration..." -ForegroundColor Cyan
python .\scripts\inspect_kuaishou_comment_regions.py --config $TestConfig
$regionCode = $LASTEXITCODE
if ($regionCode -ne 0) { $inspectCode = $regionCode }

Write-Host ""
Write-Host "[4/4] Strictly verifying Kuaishou public engagement/profile metric persistence..." -ForegroundColor Cyan
python .\scripts\inspect_kuaishou_metrics_acceptance.py --config $TestConfig
$metricCode = $LASTEXITCODE
if ($metricCode -ne 0) { $inspectCode = $metricCode }

Write-Host ""
if ($inspectCode -eq 0) {
    Write-Host "KUAISHOU REALTIME LIVE ACCEPTANCE PASSED." -ForegroundColor Green
    Write-Host "Verified: discovery, first-level comments, nested replies, parent/root, comment public region, video likes, platform comment count, follower/following and comment likes." -ForegroundColor Green
} else {
    Write-Host "Kuaishou realtime acceptance still has a blocking gap." -ForegroundColor Yellow
    if ($regionCode -ne 0) {
        Write-Host "Blocking gap: comment public IP-region has not yet been restored; do not mark Kuaishou fully accepted." -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "=== Automatic Kuaishou detail/IP-region diagnostics ===" -ForegroundColor Cyan
    $latestLogs = Get-ChildItem $platformTestRoot -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @("stdout.log", "stderr.log") } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 2
    if ($latestLogs) {
        $patterns = @(
            "KUAISHOU_SESSION_PROBE",
            "KUAISHOU_LOGIN_REQUIRED",
            "KUAISHOU_LOGIN_UI",
            "KS_COMMENT_REGION_H5",
            "KS_COMMENT_REGION_H5_MERGE",
            "KS_COMMENT_REGION_H5_FAILED",
            "KS_COMMENT_REGION_DEBUG",
            "KUAISHOU_REALTIME_DETAIL_CANDIDATE_SUCCESS",
            "KUAISHOU_REALTIME_DETAIL_CANDIDATE_FAILED",
            "REST API V2 error",
            "DataFetchError",
            "TimeoutError",
            "HTTP 502",
            "VERIFY_REQUIRED",
            "captcha"
        )
        foreach ($log in $latestLogs) {
            Write-Host "--- $($log.FullName) ---" -ForegroundColor DarkCyan
            Select-String -Path $log.FullName -Pattern $patterns -SimpleMatch -ErrorAction SilentlyContinue |
                Select-Object -Last 100 |
                ForEach-Object { $_.Line }
        }
    } else {
        Write-Host "No stdout/stderr logs found under $platformTestRoot" -ForegroundColor Yellow
    }

    if ($runCode -ne 0) {
        Write-Host ""
        Write-Host "Running automatic high-level failure diagnosis..." -ForegroundColor Cyan
        python .\scripts\diagnose_kuaishou_latest_failure.py --config $TestConfig
    }
    Write-Host "Do not start a long historical recrawl. Send the [2/4]-[4/4] JSON plus the automatic diagnostic lines above." -ForegroundColor Yellow
}

exit $inspectCode