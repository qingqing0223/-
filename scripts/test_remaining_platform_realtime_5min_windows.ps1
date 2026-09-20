param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","bili","wb","toutiao","zhihu")]
    [string]$Platform,

    [string]$BaseConfig = ".\config\monitoring.local.json"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

if (-not (Test-Path $BaseConfig)) {
    Write-Host "ERROR: base config not found: $BaseConfig" -ForegroundColor Red
    exit 2
}

$cfg = Get-Content $BaseConfig -Raw -Encoding UTF8 | ConvertFrom-Json
$MediaCrawlerRoot = [string]$cfg.media_crawler_root
if (-not $MediaCrawlerRoot) { $MediaCrawlerRoot = "E:\MediaCrawler_clean" }

Write-Host "=== Remaining-platform full capability five-minute acceptance ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "Matrix: discovery, root comments, nested replies, parent/root, public region, source type, time evolution, raw JSONL, dedupe, checkpoint/resume and five-minute timing." -ForegroundColor Yellow
Write-Host "Historical exhaustive backfill is separate from this bounded realtime test." -ForegroundColor Yellow
Write-Host ""

Write-Host "Applying/verifying shared public-region patch..." -ForegroundColor Cyan
python .\scripts\patch_mediacrawler_public_regions.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python .\scripts\patch_mediacrawler_public_regions.py --root $MediaCrawlerRoot --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($Platform -eq "xhs") {
    Write-Host "Applying/verifying XHS bounded realtime resilience patch..." -ForegroundColor Cyan
    python .\scripts\patch_xhs_realtime_resilience.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python .\scripts\patch_xhs_realtime_resilience.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "Applying/verifying XHS comment hierarchy patch..." -ForegroundColor Cyan
    python .\scripts\patch_xhs_comment_hierarchy.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python .\scripts\patch_xhs_comment_hierarchy.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "Applying/verifying XHS strict public-region patch..." -ForegroundColor Cyan
    python .\scripts\patch_xhs_public_regions.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python .\scripts\patch_xhs_public_regions.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if ($Platform -eq "wb") {
    Write-Host "Applying/verifying Weibo bounded realtime resilience patch..." -ForegroundColor Cyan
    python .\scripts\patch_weibo_realtime_resilience.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python .\scripts\patch_weibo_realtime_resilience.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "Applying/verifying Weibo comment hierarchy patch..." -ForegroundColor Cyan
    python .\scripts\patch_weibo_comment_hierarchy.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python .\scripts\patch_weibo_comment_hierarchy.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "Applying/verifying Weibo strict public-region patch..." -ForegroundColor Cyan
    python .\scripts\patch_weibo_public_regions.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python .\scripts\patch_weibo_public_regions.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if ($Platform -eq "toutiao") {
    Write-Host "Verifying native Toutiao Playwright adapter..." -ForegroundColor Cyan
    python -m py_compile .\scripts\toutiao_crawler.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    uv run --project $MediaCrawlerRoot python -c "import playwright; print('Toutiao Playwright runtime OK')"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    python -m unittest tests.test_toutiao_final_stack -v
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Set-ConfigProperty($obj, [string]$name, $value) {
    if ($obj.PSObject.Properties.Name -contains $name) {
        $obj.$name = $value
    } else {
        $obj | Add-Member -NotePropertyName $name -NotePropertyValue $value
    }
}

# The acceptance script must be self-contained even when a student's local
# config predates a newly activated platform. Use the canonical student config
# as the source of platform metadata and campaign keywords.
$canonicalConfigPath = Join-Path $RepoRoot "config\monitoring.student.windows.json"
$canonicalCfg = Get-Content $canonicalConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$activeCodes = @("xhs","dy","ks","bili","wb","toutiao","zhihu")
$platformList = @($cfg.platforms | Where-Object {
    $_ -and ($activeCodes -contains [string]$_.code)
})
$selectedEntry = $platformList | Where-Object { [string]$_.code -eq $Platform } | Select-Object -First 1
if (-not $selectedEntry) {
    $canonicalEntry = @($canonicalCfg.platforms | Where-Object {
        [string]$_.code -eq $Platform
    }) | Select-Object -First 1
    if (-not $canonicalEntry) {
        throw "Canonical config is missing selected platform '$Platform'."
    }
    $platformList += [pscustomobject]@{
        code = [string]$canonicalEntry.code
        name = [string]$canonicalEntry.name
        enabled = $true
    }
    Write-Host "Added missing platform '$Platform' to temporary acceptance config." -ForegroundColor Yellow
} else {
    $selectedEntry.enabled = $true
}
Set-ConfigProperty $cfg "platforms" $platformList
Set-ConfigProperty $cfg "keywords" @($canonicalCfg.keywords)

$policy = @{
    "xhs"   = @{ Budget = 55; Timeout = 45;  CommentCap = 100 }
    "bili"  = @{ Budget = 70; Timeout = 100; CommentCap = 300 }
    "wb"    = @{ Budget = 50; Timeout = 40;  CommentCap = 100 }
    "toutiao" = @{ Budget = 55; Timeout = 45;  CommentCap = 100 }
    "zhihu" = @{ Budget = 60; Timeout = 90;  CommentCap = 200 }
}
$p = $policy[$Platform]

$stamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$driveRoot = "E:\MediaCrawlerData"
if ([string]$cfg.data_root) {
    try {
        $existing = [System.IO.Path]::GetPathRoot([string]$cfg.data_root)
        if ($existing) { $driveRoot = Join-Path $existing "MediaCrawlerData" }
    } catch {}
}
$testDataRoot = Join-Path $driveRoot ("{0}_{1}_realtime_acceptance" -f $stamp, $Platform)
$platformTestRoot = "$testDataRoot`_$Platform"

Set-ConfigProperty $cfg "data_root" $testDataRoot
Set-ConfigProperty $cfg "results_date" ""
Set-ConfigProperty $cfg "results_date_mode" "auto"
Set-ConfigProperty $cfg "realtime_mode" $true
Set-ConfigProperty $cfg "interval_seconds" 300
Set-ConfigProperty $cfg "overrun_cooldown_seconds" 60
Set-ConfigProperty $cfg "soft_empty_cooldown_seconds" 1800
Set-ConfigProperty $cfg "network_error_cooldown_seconds" 300
if ($Platform -eq "wb") {
    Set-ConfigProperty $cfg "realtime_discovery_max_notes_count" 20
    Set-ConfigProperty $cfg "wb_realtime_discovery_max_notes_count" 20
    Set-ConfigProperty $cfg "realtime_detail_max_items_per_cycle" 3
    Set-ConfigProperty $cfg "wb_realtime_detail_max_items_per_cycle" 3
} else {
    Set-ConfigProperty $cfg "realtime_discovery_max_notes_count" 30
    Set-ConfigProperty $cfg "realtime_detail_max_items_per_cycle" 6
}
Set-ConfigProperty $cfg "realtime_detail_batch_size" 1
Set-ConfigProperty $cfg "realtime_comment_refresh_seconds" 300
Set-ConfigProperty $cfg "realtime_detail_min_start_remaining_seconds" 30
Set-ConfigProperty $cfg "get_comment" "yes"
Set-ConfigProperty $cfg "get_sub_comment" "yes"
Set-ConfigProperty $cfg "ingest_comments" $true
Set-ConfigProperty $cfg "detail_comment_recovery" $true
Set-ConfigProperty $cfg "max_concurrency_num" 1
if ($Platform -eq "xhs") {
    Set-ConfigProperty $cfg "xhs_realtime_discovery_max_notes_count" 20
    Set-ConfigProperty $cfg "xhs_realtime_items_per_keyword" 5
    Set-ConfigProperty $cfg "xhs_realtime_search_timeout_seconds" 120
    Set-ConfigProperty $cfg "xhs_realtime_detail_max_items_per_cycle" 2
    Set-ConfigProperty $cfg "xhs_realtime_detail_budget_seconds" 55
    Set-ConfigProperty $cfg "xhs_realtime_candidate_timeout_seconds" 45
    Set-ConfigProperty $cfg "xhs_realtime_max_comments_per_video" 100
    Set-ConfigProperty $cfg "classifier_concurrency" 12
    Set-ConfigProperty $cfg "network_error_cooldown_seconds" 600
    Set-ConfigProperty $cfg "overrun_cooldown_seconds" 120
}
if ($Platform -eq "toutiao") {
    Set-ConfigProperty $cfg "toutiao_realtime_discovery_max_notes_count" 10
    Set-ConfigProperty $cfg "toutiao_realtime_items_per_keyword" 4
    Set-ConfigProperty $cfg "toutiao_realtime_search_timeout_seconds" 120
    Set-ConfigProperty $cfg "toutiao_realtime_detail_max_items_per_cycle" 2
    Set-ConfigProperty $cfg "toutiao_realtime_detail_budget_seconds" 55
    Set-ConfigProperty $cfg "toutiao_realtime_candidate_timeout_seconds" 45
    Set-ConfigProperty $cfg "toutiao_realtime_max_comments_per_video" 100
    Set-ConfigProperty $cfg "toutiao_realtime_subcomment_root_cap" 3
    Set-ConfigProperty $cfg "toutiao_realtime_subcomment_page_cap" 1
    Set-ConfigProperty $cfg "classifier_concurrency" 12
    Set-ConfigProperty $cfg "overrun_cooldown_seconds" 120
}
if ($Platform -eq "wb") {
    Set-ConfigProperty $cfg "wb_realtime_discovery_max_notes_count" 10
    Set-ConfigProperty $cfg "wb_realtime_search_timeout_seconds" 100
    Set-ConfigProperty $cfg "wb_realtime_detail_max_items_per_cycle" 2
    Set-ConfigProperty $cfg "wb_realtime_detail_budget_seconds" 55
    Set-ConfigProperty $cfg "wb_realtime_candidate_timeout_seconds" 35
    Set-ConfigProperty $cfg "wb_realtime_max_comments_per_video" 100
    Set-ConfigProperty $cfg "classifier_concurrency" 12
    Set-ConfigProperty $cfg "network_error_cooldown_seconds" 600
    Set-ConfigProperty $cfg "overrun_cooldown_seconds" 120
}
Set-ConfigProperty $cfg ("{0}_realtime_detail_budget_seconds" -f $Platform) ([int]$p.Budget)
Set-ConfigProperty $cfg ("{0}_realtime_candidate_timeout_seconds" -f $Platform) ([int]$p.Timeout)
Set-ConfigProperty $cfg ("{0}_realtime_max_comments_per_video" -f $Platform) ([int]$p.CommentCap)

$TestConfig = Join-Path $RepoRoot ("config\monitoring.{0}-realtime-test.json" -f $Platform)
$json = $cfg | ConvertTo-Json -Depth 100
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($TestConfig, $json, $utf8NoBom)

Write-Host "Realtime test config: $TestConfig" -ForegroundColor Cyan
Write-Host "Realtime test data:   $platformTestRoot" -ForegroundColor Cyan
if ($Platform -eq "wb") {
    Write-Host "Discovery cap:        10 (Weibo anti-abuse bounded)" -ForegroundColor Cyan
    Write-Host "Detail candidates:    2" -ForegroundColor Cyan
} elseif ($Platform -eq "xhs") {
    Write-Host "Discovery cap:        5 items/keyword (XHS bounded)" -ForegroundColor Cyan
    Write-Host "Detail candidates:    2" -ForegroundColor Cyan
} else {
    Write-Host "Discovery cap:        30" -ForegroundColor Cyan
}
Write-Host "Detail budget:        $($p.Budget) seconds" -ForegroundColor Cyan
Write-Host "Candidate timeout:    $($p.Timeout) seconds" -ForegroundColor Cyan
Write-Host "Comment cap/item:     $($p.CommentCap)" -ForegroundColor Cyan
Write-Host ""
Write-Host "[1/2] Running one bounded realtime cycle..." -ForegroundColor Cyan
$started = Get-Date
python .\run_student_platform_final.py --platform $Platform --config $TestConfig --once
$runCode = $LASTEXITCODE
$elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
Write-Host "Wall-clock elapsed: $elapsed seconds" -ForegroundColor Cyan

Write-Host ""
Write-Host "[2/2] Inspecting complete capability matrix..." -ForegroundColor Cyan
python .\scripts\inspect_platform_capability_matrix.py --platform $Platform --config $TestConfig
$inspectCode = $LASTEXITCODE

if ($inspectCode -eq 0) {
    Write-Host ""
    Write-Host "$($Platform.ToUpper()) FULL CAPABILITY REALTIME ACCEPTANCE PASSED." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "$($Platform.ToUpper()) acceptance has one or more blocking gaps." -ForegroundColor Yellow
    Write-Host "=== Automatic platform diagnostics ===" -ForegroundColor Cyan
    $latestLogs = Get-ChildItem $platformTestRoot -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @("stdout.log", "stderr.log") } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 2
    $patterns = @(
        "REALTIME_DETAIL",
        "DETAIL_COMMENT_RECOVERY",
        "DataFetchError",
        "TimeoutError",
        "VERIFY_REQUIRED",
        "LOGIN_REQUIRED",
        "captcha",
        "verification",
        "security verification",
        "ip_location",
        "ip_label",
        "ip_region"
    )
    foreach ($log in $latestLogs) {
        Write-Host "--- $($log.FullName) ---" -ForegroundColor DarkCyan
        Select-String -Path $log.FullName -Pattern $patterns -SimpleMatch -ErrorAction SilentlyContinue |
            Select-Object -Last 120 |
            ForEach-Object { $_.Line }
    }
    Write-Host "Do not start a long historical recrawl. Send the [2/2] JSON and diagnostic lines above." -ForegroundColor Yellow
}

if ($runCode -ne 0 -and $inspectCode -eq 0) {
    Write-Host "Collector returned non-zero, but persisted acceptance data passed. Review diagnostics before production use." -ForegroundColor Yellow
}

exit $inspectCode
