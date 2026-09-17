param(
    [string]$BaseConfig = ".\config\monitoring.local.json"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

if (-not (Test-Path $BaseConfig)) {
    Write-Host "ERROR: base Douyin config not found: $BaseConfig" -ForegroundColor Red
    exit 2
}

$cfg = Get-Content $BaseConfig -Raw -Encoding UTF8 | ConvertFrom-Json
$MediaCrawlerRoot = [string]$cfg.media_crawler_root
if (-not $MediaCrawlerRoot) { $MediaCrawlerRoot = "E:\MediaCrawler_clean" }

Write-Host "=== Douyin full-function five-minute realtime acceptance ===" -ForegroundColor Cyan
Write-Host "This is one bounded realtime cycle, not historical full backfill." -ForegroundColor Yellow
Write-Host "Matrix: discovery, root comments, nested replies, parent/root, public region, source type, raw JSONL, dedupe, five-minute timing." -ForegroundColor Yellow
Write-Host ""

Write-Host "Applying/verifying shared public-region patch..." -ForegroundColor Cyan
python .\scripts\patch_mediacrawler_public_regions.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python .\scripts\patch_mediacrawler_public_regions.py --root $MediaCrawlerRoot --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Applying/verifying Douyin parent/root hierarchy patch..." -ForegroundColor Cyan
python .\scripts\patch_douyin_comment_hierarchy.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python .\scripts\patch_douyin_comment_hierarchy.py --root $MediaCrawlerRoot --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

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
$testDataRoot = Join-Path $driveRoot ("{0}_dy_realtime_acceptance" -f $stamp)
$platformTestRoot = "$testDataRoot`_dy"

Set-ConfigProperty $cfg "data_root" $testDataRoot
Set-ConfigProperty $cfg "results_date" ""
Set-ConfigProperty $cfg "results_date_mode" "auto"
Set-ConfigProperty $cfg "realtime_mode" $true
Set-ConfigProperty $cfg "interval_seconds" 300
Set-ConfigProperty $cfg "realtime_discovery_max_notes_count" 40
Set-ConfigProperty $cfg "realtime_detail_max_items_per_cycle" 6
Set-ConfigProperty $cfg "realtime_detail_batch_size" 1
Set-ConfigProperty $cfg "realtime_comment_refresh_seconds" 300
Set-ConfigProperty $cfg "douyin_realtime_detail_budget_seconds" 120
Set-ConfigProperty $cfg "douyin_realtime_max_comments_per_video" 300
Set-ConfigProperty $cfg "get_comment" "yes"
Set-ConfigProperty $cfg "get_sub_comment" "yes"
Set-ConfigProperty $cfg "ingest_comments" $true
Set-ConfigProperty $cfg "max_concurrency_num" 1

$TestConfig = Join-Path $RepoRoot "config\monitoring.dy-realtime-test.json"
$json = $cfg | ConvertTo-Json -Depth 100
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($TestConfig, $json, $utf8NoBom)

Write-Host "Realtime test config: $TestConfig" -ForegroundColor Cyan
Write-Host "Realtime test data:   $platformTestRoot" -ForegroundColor Cyan
Write-Host ""
Write-Host "[1/2] Running one bounded Douyin realtime cycle..." -ForegroundColor Cyan
$started = Get-Date
python .\run_single_platform.py --platform dy --config $TestConfig --once
$runCode = $LASTEXITCODE
$elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
Write-Host "Wall-clock elapsed: $elapsed seconds" -ForegroundColor Cyan

Write-Host ""
Write-Host "[2/2] Inspecting complete Douyin function matrix..." -ForegroundColor Cyan
python .\scripts\inspect_douyin_acceptance.py --config $TestConfig
$inspectCode = $LASTEXITCODE

if ($inspectCode -eq 0) {
    Write-Host "" 
    Write-Host "DOUYIN FULL FUNCTION REALTIME ACCEPTANCE PASSED." -ForegroundColor Green
    Write-Host "The cycle proved five-minute discovery, comments, nested hierarchy, public region, source types, raw JSONL and queue execution." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Douyin acceptance has one or more blocking gaps." -ForegroundColor Yellow
    Write-Host "=== Automatic Douyin diagnostics ===" -ForegroundColor Cyan
    $latestLogs = Get-ChildItem $platformTestRoot -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @("stdout.log", "stderr.log") } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 2
    $patterns = @(
        "DOUYIN_REALTIME_DETAIL",
        "DataFetchError",
        "TimeoutError",
        "VERIFY_REQUIRED",
        "LOGIN_REQUIRED",
        "captcha",
        "verification",
        "account blocked",
        "ip_label",
        "ip_location"
    )
    foreach ($log in $latestLogs) {
        Write-Host "--- $($log.FullName) ---" -ForegroundColor DarkCyan
        Select-String -Path $log.FullName -Pattern $patterns -SimpleMatch -ErrorAction SilentlyContinue |
            Select-Object -Last 100 |
            ForEach-Object { $_.Line }
    }
    Write-Host "Do not start a long historical recrawl. Send the [2/2] JSON and diagnostic lines above." -ForegroundColor Yellow
}

if ($runCode -ne 0 -and $inspectCode -eq 0) {
    Write-Host "Collector returned non-zero, but persisted acceptance data passed. Review diagnostics before production use." -ForegroundColor Yellow
}

exit $inspectCode
