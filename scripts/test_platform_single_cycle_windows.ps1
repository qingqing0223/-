param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","toutiao","zhihu")]
    [string]$Platform,

    [string]$Keyword = "",
    [string]$Config = ".\config\monitoring.windows.json"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

if ([string]::IsNullOrWhiteSpace($Keyword)) {
    $Keyword = -join @(
        [char]0x6C11, [char]0x65CF, [char]0x56E2, [char]0x7ED3,
        [char]0x8FDB, [char]0x6B65, [char]0x5BA3, [char]0x4F20,
        [char]0x5468
    )
}

if (-not $env:DASHSCOPE_API_KEY) {
    Write-Host "ERROR: DASHSCOPE_API_KEY is not set." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $Config)) {
    Write-Host "ERROR: config not found: $Config" -ForegroundColor Red
    exit 1
}

Write-Host "=== Seven-platform one-cycle full-chain test ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "Keyword:  $Keyword" -ForegroundColor Cyan
Write-Host "Config:   $Config" -ForegroundColor Cyan

python .\scripts\check_suqi_dashboard.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Suqi backend is not available. Start server.py --no-sim first." -ForegroundColor Red
    exit 1
}

python .\run_single_platform.py --platform $Platform --config $Config --keyword $Keyword --once
$runExit = $LASTEXITCODE

$cfgObj = Get-Content $Config -Raw -Encoding UTF8 | ConvertFrom-Json
$baseRoot = [System.IO.DirectoryInfo]$cfgObj.data_root
$dataRoot = Join-Path $baseRoot.Parent.FullName ($baseRoot.Name + "_" + $Platform)
$statusPath = Join-Path $dataRoot "status\latest_status.json"

Write-Host ""
Write-Host "=== Test summary ===" -ForegroundColor Cyan
if (Test-Path $statusPath) {
    $status = Get-Content $statusPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $run = $status.platform_runs | Select-Object -First 1
    $ingest = $status.ingest | Select-Object -First 1
    $push = $status.dashboard_push

    [PSCustomObject]@{
        platform = $Platform
        crawler_status = $run.status
        crawler_state = $run.state
        return_code = $run.return_code
        duration_seconds = $run.duration_seconds
        new_records = $ingest.new_records
        classified_records = $ingest.classified_records
        region_records = $ingest.region_records
        region_rate = $ingest.region_rate
        minority_language_records = $ingest.minority_language_records
        dashboard_ok = $push.ok
        dashboard_sent = $push.sent
        dashboard_inserted = $push.inserted
        dashboard_skipped = $push.skipped
        outbox_after = $push.outbox_after
        status_file = $statusPath
    } | Format-List

    if ($run.state -eq "VERIFY_REQUIRED" -or $run.state -eq "LOGIN_REQUIRED") {
        Write-Host "ACTION: complete the platform's official login/verification manually, then rerun once." -ForegroundColor Yellow
    } elseif ($run.status -eq "ok" -and $push.ok -eq $true) {
        Write-Host "FULL-CHAIN TRANSPORT: PASS (crawler -> classify -> dashboard push)." -ForegroundColor Green
        if ([int]$ingest.classified_records -eq 0) {
            Write-Host "NOTE: transport passed but this keyword returned no new classifiable records in this cycle." -ForegroundColor Yellow
        }
    } else {
        Write-Host "RESULT: needs review. Send this summary plus stdout/stderr log screenshot." -ForegroundColor Yellow
    }
} else {
    Write-Host "ERROR: status file was not generated: $statusPath" -ForegroundColor Red
}

exit $runExit
