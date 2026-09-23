param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","toutiao","zhihu")]
    [string]$Platform,

    [string]$Config = ".\config\monitoring.local.json"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

if (-not (Test-Path $Config)) {
    Write-Host "ERROR: config not found: $Config" -ForegroundColor Red
    exit 1
}

$cfg = Get-Content $Config -Raw -Encoding UTF8 | ConvertFrom-Json
function Set-Prop($obj, [string]$name, $value) {
    if ($obj.PSObject.Properties.Name -contains $name) { $obj.$name = $value }
    else { $obj | Add-Member -NotePropertyName $name -NotePropertyValue $value }
}

# One-time historical catch-up. It is intentionally NOT constrained by the five-minute SLA.
Set-Prop $cfg "realtime_mode" $false
Set-Prop $cfg "search_until_exhausted" $true
Set-Prop $cfg "crawler_max_notes_count" 100000
Set-Prop $cfg "comments_until_exhausted" $true
Set-Prop $cfg "max_comments_count_singlenotes" 100000
Set-Prop $cfg "get_comment" "yes"
Set-Prop $cfg "get_sub_comment" "yes"
Set-Prop $cfg "ingest_comments" $true
Set-Prop $cfg "detail_comment_recovery" $true
Set-Prop $cfg "detail_comment_recovery_max_items" 100000
Set-Prop $cfg "detail_comment_recovery_batch_size" 10

$temp = Join-Path ([System.IO.Path]::GetTempPath()) ("promotion_week_backfill_" + $Platform + "_" + [guid]::NewGuid().ToString("N") + ".json")
$json = $cfg | ConvertTo-Json -Depth 100
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($temp, $json, $utf8NoBom)

Write-Host "=== ONE-TIME INITIAL BACKFILL ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "This pass performs natural-end historical search + first-level comments + nested comments." -ForegroundColor Yellow
Write-Host "It may take longer than five minutes. Run it once before starting the five-minute realtime watchdog." -ForegroundColor Yellow

if ($Platform -eq "bili") {
    $MediaCrawlerRoot = [string]$cfg.media_crawler_root
    if (-not $MediaCrawlerRoot -or -not (Test-Path (Join-Path $MediaCrawlerRoot "main.py"))) {
        Write-Host "ERROR: invalid media_crawler_root: $MediaCrawlerRoot" -ForegroundColor Red
        exit 3
    }

    Write-Host "Preparing Bilibili full backfill patch stack..." -ForegroundColor Cyan
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
        python (Join-Path ".\scripts" $patch) --root $MediaCrawlerRoot
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        python (Join-Path ".\scripts" $patch) --root $MediaCrawlerRoot --check
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    python .\scripts\patch_mediacrawler_public_regions.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python .\scripts\verify_mediacrawler_public_regions.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "Bilibili full backfill will use the formal monitoring window, natural-end video search, all first-level comments, and all nested replies subject only to the large safety caps." -ForegroundColor Green
}

try {
    python .\run_single_platform.py --platform $Platform --config $temp --once
    exit $LASTEXITCODE
}
finally {
    Remove-Item $temp -Force -ErrorAction SilentlyContinue
}
