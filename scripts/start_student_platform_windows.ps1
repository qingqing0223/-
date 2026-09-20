param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","toutiao","zhihu")]
    [string]$Platform,

    [string]$NodeId = $env:COMPUTERNAME,
    [string]$Config = ".\config\monitoring.student.windows.json",
    [switch]$PushGithub,
    [switch]$ArchiveRaw,
    [string]$RawArchiveRepo = $env:PROMOTION_RAW_ARCHIVE_REPO,
    [switch]$PrivateRepoConfirmed,
    [switch]$ReviewSync,
    [string]$ReviewRepo = $env:PROMOTION_REVIEW_REPO,
    [switch]$PrivateReviewRepoConfirmed,
    [switch]$NoWatchdog
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

if (-not (Test-Path $Config)) {
    Write-Host "ERROR: config not found: $Config" -ForegroundColor Red
    exit 1
}
if (-not $NodeId) {
    $NodeId = "student-node"
}

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "ERROR: python was not found in this PowerShell session." -ForegroundColor Red
    exit 1
}
$PythonExe = $pythonCmd.Source
Write-Host "Python:   $PythonExe" -ForegroundColor Cyan

$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $PythonExe -c "import opinion_monitor_v2" 2>$null
$importCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference

if ($importCode -ne 0) {
    Write-Host "Local classifier package is missing; installing packages/v2..." -ForegroundColor Yellow
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $PythonExe -m pip install -e (Join-Path $RepoRoot "packages\v2")
    $installCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    if ($installCode -ne 0) {
        Write-Host "ERROR: failed to install packages/v2." -ForegroundColor Red
        exit $installCode
    }
}

if (-not $env:DASHSCOPE_API_KEY) {
    Write-Host "DASHSCOPE_API_KEY is not set. Collection will still run; attitude classification will be preserved as unclassified/degraded until the model service is available." -ForegroundColor Yellow
}

# Upgrade machine-local configs to the final five-minute/full-capability matrix.
# Historical exhaustive backfill remains a separate one-time job. The realtime loop
# only uses bounded discovery/detail limits, so these high natural-end caps do not
# block the five-minute discovery SLA.
$resolvedConfig = (Resolve-Path $Config).Path
if ([System.IO.Path]::GetFileName($resolvedConfig) -like "*.local.json") {
    $cfgObj = Get-Content $resolvedConfig -Raw -Encoding UTF8 | ConvertFrom-Json
    function Set-ConfigProperty($obj, [string]$name, $value) {
        if ($obj.PSObject.Properties.Name -contains $name) {
            $obj.$name = $value
        } else {
            $obj | Add-Member -NotePropertyName $name -NotePropertyValue $value
        }
    }
    Set-ConfigProperty $cfgObj "event_id" "promotion_week_2026_preheat"
    Set-ConfigProperty $cfgObj "event_name" "2026年民族团结进步宣传周预热阶段舆情监测"
    Set-ConfigProperty $cfgObj "monitoring_start_time" "2026-09-16T00:00:00+08:00"
    Set-ConfigProperty $cfgObj "results_date" ""
    Set-ConfigProperty $cfgObj "results_date_mode" "auto"
    Set-ConfigProperty $cfgObj "interval_seconds" 300
    Set-ConfigProperty $cfgObj "overrun_cooldown_seconds" 60
    Set-ConfigProperty $cfgObj "soft_empty_cooldown_seconds" 300
    Set-ConfigProperty $cfgObj "network_error_cooldown_seconds" 300
    Set-ConfigProperty $cfgObj "realtime_mode" $true
    Set-ConfigProperty $cfgObj "realtime_discovery_max_notes_count" 30
    Set-ConfigProperty $cfgObj "realtime_detail_max_items_per_cycle" 6
    Set-ConfigProperty $cfgObj "realtime_detail_batch_size" 1
    Set-ConfigProperty $cfgObj "realtime_comment_refresh_seconds" 300
    Set-ConfigProperty $cfgObj "realtime_detail_min_start_remaining_seconds" 30
    Set-ConfigProperty $cfgObj "search_until_exhausted" $true
    Set-ConfigProperty $cfgObj "crawler_max_notes_count" 100000
    Set-ConfigProperty $cfgObj "comments_until_exhausted" $true
    Set-ConfigProperty $cfgObj "max_comments_count_singlenotes" 100000
    Set-ConfigProperty $cfgObj "get_comment" "yes"
    Set-ConfigProperty $cfgObj "get_sub_comment" "yes"
    Set-ConfigProperty $cfgObj "ingest_comments" $true
    Set-ConfigProperty $cfgObj "detail_comment_recovery" $true
    Set-ConfigProperty $cfgObj "detail_comment_recovery_max_items" 30
    Set-ConfigProperty $cfgObj "detail_comment_recovery_batch_size" 1
    Set-ConfigProperty $cfgObj "github_diagnostic_samples" $true
    Set-ConfigProperty $cfgObj "github_diagnostic_sample_rows_per_type" 5
    Set-ConfigProperty $cfgObj "max_concurrency_num" 1
    if ($Platform -eq "wb") {
        Set-ConfigProperty $cfgObj "network_error_cooldown_seconds" 600
        Set-ConfigProperty $cfgObj "overrun_cooldown_seconds" 120
        Set-ConfigProperty $cfgObj "classifier_concurrency" 12
    }
    if ($Platform -eq "xhs") {
        Set-ConfigProperty $cfgObj "network_error_cooldown_seconds" 600
        Set-ConfigProperty $cfgObj "overrun_cooldown_seconds" 120
        Set-ConfigProperty $cfgObj "classifier_concurrency" 12
    }
    if ($Platform -eq "toutiao") {
        Set-ConfigProperty $cfgObj "classifier_concurrency" 12
        Set-ConfigProperty $cfgObj "network_error_cooldown_seconds" 600
        Set-ConfigProperty $cfgObj "overrun_cooldown_seconds" 120
    }

    # Per-platform realtime budgets. These are soft phase budgets: a candidate
    # already in progress is allowed to finish up to its candidate timeout, while
    # new candidates are not started once the soft budget is nearly exhausted.
    Set-ConfigProperty $cfgObj "xhs_realtime_discovery_max_notes_count" 20
    Set-ConfigProperty $cfgObj "xhs_realtime_items_per_keyword" 5
    Set-ConfigProperty $cfgObj "xhs_realtime_search_timeout_seconds" 120
    Set-ConfigProperty $cfgObj "xhs_realtime_detail_max_items_per_cycle" 2
    Set-ConfigProperty $cfgObj "xhs_realtime_detail_budget_seconds" 55
    Set-ConfigProperty $cfgObj "xhs_realtime_candidate_timeout_seconds" 45
    Set-ConfigProperty $cfgObj "xhs_realtime_max_comments_per_video" 100
    Set-ConfigProperty $cfgObj "dy_realtime_detail_budget_seconds" 70
    Set-ConfigProperty $cfgObj "dy_realtime_candidate_timeout_seconds" 105
    Set-ConfigProperty $cfgObj "dy_realtime_max_comments_per_video" 200
    # Bilibili search fetches one fixed page (up to 20 videos) per keyword and
    # sleeps inside each video-detail task.  A single worker made six-keyword
    # discovery exceed the five-minute SLA, so realtime search uses modest
    # platform-local concurrency without changing other platforms or historical backfill.
    Set-ConfigProperty $cfgObj "bili_realtime_discovery_max_notes_count" 20
    Set-ConfigProperty $cfgObj "bili_realtime_search_concurrency" 4
    Set-ConfigProperty $cfgObj "bili_realtime_items_per_keyword" 5
    Set-ConfigProperty $cfgObj "bili_realtime_detail_budget_seconds" 70
    Set-ConfigProperty $cfgObj "bili_realtime_candidate_timeout_seconds" 100
    Set-ConfigProperty $cfgObj "bili_realtime_max_comments_per_video" 20
    Set-ConfigProperty $cfgObj "bili_realtime_subcomment_root_cap" 2
    Set-ConfigProperty $cfgObj "bili_realtime_subcomment_page_cap" 1
    Set-ConfigProperty $cfgObj "wb_realtime_discovery_max_notes_count" 10
    Set-ConfigProperty $cfgObj "wb_realtime_search_timeout_seconds" 100
    Set-ConfigProperty $cfgObj "wb_realtime_detail_max_items_per_cycle" 2
    Set-ConfigProperty $cfgObj "wb_realtime_detail_budget_seconds" 55
    Set-ConfigProperty $cfgObj "wb_realtime_candidate_timeout_seconds" 35
    Set-ConfigProperty $cfgObj "wb_realtime_max_comments_per_video" 100
    Set-ConfigProperty $cfgObj "toutiao_realtime_discovery_max_notes_count" 12
    Set-ConfigProperty $cfgObj "toutiao_realtime_search_timeout_seconds" 180
    Set-ConfigProperty $cfgObj "toutiao_realtime_detail_max_items_per_cycle" 2
    Set-ConfigProperty $cfgObj "toutiao_realtime_detail_budget_seconds" 70
    Set-ConfigProperty $cfgObj "toutiao_realtime_candidate_timeout_seconds" 90
    Set-ConfigProperty $cfgObj "toutiao_realtime_max_comments_per_video" 100
    Set-ConfigProperty $cfgObj "zhihu_realtime_detail_budget_seconds" 60
    Set-ConfigProperty $cfgObj "zhihu_realtime_candidate_timeout_seconds" 90
    Set-ConfigProperty $cfgObj "zhihu_realtime_max_comments_per_video" 200

    $json = $cfgObj | ConvertTo-Json -Depth 100
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($resolvedConfig, $json, $utf8NoBom)
    Write-Host "Local config upgraded to final five-minute realtime + queued deep-comment matrix." -ForegroundColor Green
}

try {
    $existing = Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.Name -match "python" -and $_.CommandLine -and
        ($_.CommandLine -match "run_single_platform.py" -or $_.CommandLine -match "run_student_platform_final.py") -and
        $_.CommandLine -match "--platform\s+$Platform(\s|$)"
    }
    if ($existing) {
        Write-Host "ERROR: another $Platform collector is already running on this machine." -ForegroundColor Red
        Write-Host "Stop the old monitoring window first, then start the final version once." -ForegroundColor Yellow
        exit 2
    }
} catch {
    Write-Host "Warning: duplicate-process check unavailable; continuing." -ForegroundColor Yellow
}

Write-Host "Running final preflight..." -ForegroundColor Cyan
& $PythonExe .\scripts\preflight.py --config $Config
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: preflight failed. Do not start monitoring until required_failures is 0." -ForegroundColor Red
    exit $LASTEXITCODE
}

if ($ArchiveRaw) {
    if (-not $RawArchiveRepo) {
        Write-Host "ERROR: -ArchiveRaw requires -RawArchiveRepo or environment variable PROMOTION_RAW_ARCHIVE_REPO." -ForegroundColor Red
        exit 30
    }
    if (-not $PrivateRepoConfirmed) {
        Write-Host "ERROR: raw JSONL must only be pushed to an access-controlled PRIVATE Git repository." -ForegroundColor Red
        Write-Host "After confirming privacy, rerun with -PrivateRepoConfirmed." -ForegroundColor Yellow
        exit 31
    }
    if (-not (Test-Path (Join-Path $RawArchiveRepo ".git"))) {
        Write-Host "ERROR: private raw archive repository is not cloned at: $RawArchiveRepo" -ForegroundColor Red
        exit 32
    }
}

if ($ReviewSync) {
    if (-not $ReviewRepo) {
        Write-Host "ERROR: -ReviewSync requires -ReviewRepo or environment variable PROMOTION_REVIEW_REPO." -ForegroundColor Red
        exit 33
    }
    if (-not $PrivateReviewRepoConfirmed) {
        Write-Host "ERROR: non-support review text/URLs must only be pushed to an access-controlled PRIVATE Git repository." -ForegroundColor Red
        Write-Host "After confirming privacy, rerun with -PrivateReviewRepoConfirmed." -ForegroundColor Yellow
        exit 34
    }
    if (-not (Test-Path (Join-Path $ReviewRepo ".git"))) {
        Write-Host "ERROR: private review repository is not cloned at: $ReviewRepo" -ForegroundColor Red
        exit 35
    }
}

Write-Host "=== FINAL student distributed platform monitor ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "NodeId:   $NodeId" -ForegroundColor Cyan
Write-Host "Config:   $Config" -ForegroundColor Cyan
Write-Host "Realtime target: complete discovery + bounded deep-comment + ingestion cycle within 300 seconds." -ForegroundColor Yellow
Write-Host "Enabled: six-keyword discovery, first-level comments, nested replies, parent/root hierarchy, public coarse IP-region fields when exposed, source/content type reporting, engagement/time fields, dedupe, checkpoint/resume, persistent deep queue and GitHub aggregate sync." -ForegroundColor Yellow
Write-Host "Timeout/non-zero detail candidates are isolated; partial JSONL from interrupted candidates is rolled back and the candidate remains retryable." -ForegroundColor Yellow
Write-Host "Historical exhaustive backfill is separate from realtime. It can page toward natural end without blocking five-minute new-content discovery." -ForegroundColor Yellow
Write-Host "Official login/captcha/security verification must be completed manually when requested; automatic bypass is not used." -ForegroundColor Yellow
Write-Host "Full raw JSONL stays local by default. Public GitHub receives aggregate/privacy-safe monitoring results only." -ForegroundColor Yellow

if ($PushGithub) {
    $syncCmd = "Set-Location '$RepoRoot'; .\scripts\watch_node_results_sync_windows.ps1 -Platform $Platform -NodeId '$NodeId' -Config '$Config'"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $syncCmd
    Write-Host "Public GitHub aggregate + privacy-safe diagnostic sync watchdog started in a separate window (immediate + every 300s; transient failures auto-restart)." -ForegroundColor Green
} else {
    Write-Host "Public GitHub result push is OFF. Add -PushGithub after this machine has Git write access." -ForegroundColor Yellow
}

if ($ReviewSync) {
    $reviewCmd = "Set-Location '$RepoRoot'; .\scripts\start_private_non_support_review_sync_windows.ps1 -Platform $Platform -NodeId '$NodeId' -Config '$Config' -ReviewRepo '$ReviewRepo' -PrivateRepoConfirmed"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $reviewCmd
    Write-Host "PRIVATE non-support review sync started in a separate window (immediate + every 300s)." -ForegroundColor Green
    Write-Host "Students review non_support_manual_review.csv; confirmed rows flow into confirmed_non_support.json." -ForegroundColor Green
}

if ($ArchiveRaw) {
    $rawCmd = "Set-Location '$RepoRoot'; .\scripts\start_private_raw_archive_sync_windows.ps1 -Platform $Platform -NodeId '$NodeId' -Config '$Config' -ArchiveRepo '$RawArchiveRepo' -Push -PrivateRepoConfirmed"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $rawCmd
    Write-Host "PRIVATE full raw JSONL archive sync started in a separate window (300s)." -ForegroundColor Green
} else {
    Write-Host "Full raw JSONL remains local under the configured MediaCrawlerData directory." -ForegroundColor Yellow
}

if (-not $ReviewSync) {
    Write-Host "Private non-support review sync is OFF. Public GitHub still receives tri-class aggregates/fingerprints, but no review text." -ForegroundColor Yellow
}

if ($NoWatchdog) {
    & $PythonExe .\run_student_platform_final.py --platform $Platform --config $Config
} else {
    .\scripts\watch_student_platform_final_windows.ps1 -Platform $Platform -Config $Config
}
