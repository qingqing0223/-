param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","tieba","zhihu")]
    [string]$Platform,

    [Parameter(Mandatory=$true)]
    [string]$ArchiveRepo,

    [string]$NodeId = $env:COMPUTERNAME,
    [string]$Config = ".\config\monitoring.student.windows.json",
    [int]$IntervalSeconds = 300,
    [switch]$Push,
    [switch]$PrivateRepoConfirmed
)

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

if ($IntervalSeconds -ne 300) {
    Write-Host "ERROR: IntervalSeconds must be exactly 300 seconds." -ForegroundColor Red
    exit 1
}
if (-not $PrivateRepoConfirmed) {
    Write-Host "ERROR: full raw JSONL may contain user-generated text; use only an access-controlled PRIVATE Git repository." -ForegroundColor Red
    Write-Host "After confirming the archive repository is private, rerun with -PrivateRepoConfirmed." -ForegroundColor Yellow
    exit 2
}
if (-not (Test-Path (Join-Path $ArchiveRepo ".git"))) {
    Write-Host "ERROR: ArchiveRepo is not a cloned Git repository: $ArchiveRepo" -ForegroundColor Red
    exit 3
}
if (-not (Test-Path $Config)) {
    Write-Host "ERROR: config not found: $Config" -ForegroundColor Red
    exit 4
}

Write-Host "Starting PRIVATE raw JSONL archive sync" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "NodeId:   $NodeId" -ForegroundColor Cyan
Write-Host "Archive:  $ArchiveRepo" -ForegroundColor Cyan
Write-Host "Interval: 300 seconds" -ForegroundColor Cyan
Write-Host "Only raw_runs/*.jsonl plus latest_status.json are archived; cookies, browser_data, login state, screenshots, stdout/stderr logs and secrets are excluded." -ForegroundColor Yellow
Write-Host "JSONL is gzip-compressed and stored by node/platform/date/cycle with SHA-256 + row-count manifest." -ForegroundColor Yellow

$argsList = @(
    ".\scripts\archive_raw_runs_to_git.py",
    "--platform", $Platform,
    "--node-id", $NodeId,
    "--config", $Config,
    "--archive-repo", $ArchiveRepo,
    "--private-repo-confirmed",
    "--loop",
    "--interval", "300"
)
if ($Push) {
    $argsList += "--push"
    Write-Host "Git push enabled; this computer must have write access to the PRIVATE raw-data repository." -ForegroundColor Green
} else {
    Write-Host "Git push disabled; files will only be copied into the local private archive clone." -ForegroundColor Yellow
}

python @argsList
