param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","toutiao","zhihu")]
    [string]$Platform,

    [Parameter(Mandatory=$true)]
    [string]$NodeId,

    [Parameter(Mandatory=$true)]
    [string]$ReviewRepo,

    [string]$Config = ".\\config\\monitoring.local.json",
    [int]$IntervalSeconds = 300,
    [switch]$PrivateRepoConfirmed
)

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\\.."

if ($IntervalSeconds -ne 300) {
    Write-Host "ERROR: IntervalSeconds must be exactly 300 seconds." -ForegroundColor Red
    exit 1
}
if (-not $PrivateRepoConfirmed) {
    Write-Host "ERROR: review text must only be pushed to an access-controlled PRIVATE Git repository." -ForegroundColor Red
    exit 2
}
if (-not (Test-Path (Join-Path $ReviewRepo ".git"))) {
    Write-Host "ERROR: ReviewRepo is not a cloned Git repository: $ReviewRepo" -ForegroundColor Red
    exit 3
}
if (-not (Test-Path $Config)) {
    Write-Host "ERROR: config not found: $Config" -ForegroundColor Red
    exit 4
}

Write-Host "Starting PRIVATE non-support review sync" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "NodeId:   $NodeId" -ForegroundColor Cyan
Write-Host "Review:   $ReviewRepo" -ForegroundColor Cyan
Write-Host "Interval: 300 seconds" -ForegroundColor Cyan
Write-Host "Auto output: latest_non_support_review_queue.json" -ForegroundColor Green
Write-Host "Manual sheet: non_support_manual_review.csv" -ForegroundColor Green
Write-Host "Confirmed output: confirmed_non_support.json" -ForegroundColor Green
Write-Host "Only this PRIVATE repo contains review text/URLs. Public code repo keeps aggregate + privacy-safe fingerprints only." -ForegroundColor Yellow

python .\\scripts\\sync_non_support_review_private.py `
    --platform $Platform `
    --node-id $NodeId `
    --config $Config `
    --review-repo $ReviewRepo `
    --private-repo-confirmed `
    --push `
    --loop `
    --interval 300

exit $LASTEXITCODE
