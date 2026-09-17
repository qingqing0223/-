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
Write-Host ""

Write-Host "Applying/verifying Kuaishou startup resilience patch..." -ForegroundColor Cyan
python .\scripts\patch_kuaishou_startup_resilience.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python .\scripts\patch_kuaishou_startup_resilience.py --root $MediaCrawlerRoot --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Applying/verifying current Kuaishou comment/hierarchy patch..." -ForegroundColor Cyan
python .\scripts\patch_kuaishou_comment_hierarchy.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python .\scripts\patch_kuaishou_comment_hierarchy.py --root $MediaCrawlerRoot --check
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
$testDataRoot = Join-Path $driveRoot ("{0}_ks_realtime_acceptance" -f $stamp)

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
Write-Host "Realtime test data:   $testDataRoot`_ks" -ForegroundColor Cyan
Write-Host ""
Write-Host "[1/2] Running one bounded realtime cycle..." -ForegroundColor Cyan
$started = Get-Date
python .\run_single_platform.py --platform ks --config $TestConfig --once
$runCode = $LASTEXITCODE
$elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
Write-Host "Wall-clock elapsed: $elapsed seconds" -ForegroundColor Cyan
if ($runCode -ne 0) {
    Write-Host "Collector returned non-zero. Acceptance inspection will still run because partial raw JSONL may be valid." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[2/2] Inspecting five-minute + comments + hierarchy acceptance..." -ForegroundColor Cyan
python .\scripts\inspect_kuaishou_acceptance.py --config $TestConfig
$inspectCode = $LASTEXITCODE

Write-Host ""
if ($inspectCode -eq 0) {
    Write-Host "KUAISHOU REALTIME LIVE ACCEPTANCE PASSED." -ForegroundColor Green
    Write-Host "Next: inspect public IP-region availability and then configure GitHub result/raw synchronization." -ForegroundColor Green
} else {
    Write-Host "Kuaishou realtime live acceptance still has a blocking gap." -ForegroundColor Yellow
    Write-Host "Running automatic failure diagnosis from the latest stdout/stderr logs..." -ForegroundColor Cyan
    python .\scripts\diagnose_kuaishou_latest_failure.py --config $TestConfig
    Write-Host "Do not start a long historical recrawl. Send the diagnosis output above." -ForegroundColor Yellow
}

exit $inspectCode
