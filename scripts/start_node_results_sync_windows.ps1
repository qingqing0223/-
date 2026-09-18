param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","tieba","zhihu","wechat_mp","wechat_channels")]
    [string]$Platform,

    [string]$NodeId = $env:COMPUTERNAME,
    [int]$IntervalSeconds = 300,
    [switch]$Push,
    [string]$Config = ".\config\monitoring.student.windows.json"
)

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

if ($IntervalSeconds -ne 300) {
    Write-Host "ERROR: IntervalSeconds must be exactly 300 seconds for this monitoring task." -ForegroundColor Red
    exit 1
}
if (-not $NodeId) {
    $NodeId = "student-node"
}
if (-not (Test-Path $Config)) {
    Write-Host "ERROR: config not found: $Config" -ForegroundColor Red
    exit 1
}

Write-Host "Starting distributed GitHub result sync" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "NodeId:   $NodeId" -ForegroundColor Cyan
Write-Host "Interval: $IntervalSeconds seconds (fixed five-minute sync)" -ForegroundColor Cyan
Write-Host "GitHub receives aggregate monitoring JSON plus privacy-safe raw diagnostics: raw JSONL filenames, row counts, file hashes, field/schema samples, stable hashes for content/comment/reply links, public coarse IP-region fields, and nested field names." -ForegroundColor Yellow
Write-Host "Raw post/comment text, raw user identifiers, raw URLs, real IP addresses, and precise locations are NOT published to this public repository." -ForegroundColor Yellow
Write-Host "Full original JSONL remains on the student machine for local retention; use a separate PRIVATE data repository if full raw archival is later required." -ForegroundColor Yellow

$argsList = @(
    ".\scripts\publish_node_result_to_github.py",
    "--platform", $Platform,
    "--node-id", $NodeId,
    "--config", $Config,
    "--loop",
    "--interval", $IntervalSeconds
)
if ($Push) {
    $argsList += "--push"
    Write-Host "Git push enabled. This computer must authenticate with its own GitHub account that has write access." -ForegroundColor Yellow

    # One-time GitHub push authentication preflight.
    # Let Git Credential Manager open the browser once here. After it succeeds,
    # the long-running 300-second sync loop is made non-interactive so it cannot
    # reopen a browser every cycle if the credential cache/helper is unhealthy.
    $branch = (git rev-parse --abbrev-ref HEAD).Trim()
    if (-not $branch -or $branch -eq "HEAD") {
        Write-Host "ERROR: repository is not on a normal branch; cannot preflight GitHub push authentication." -ForegroundColor Red
        exit 12
    }
    Write-Host "Checking GitHub push authentication once before the sync loop..." -ForegroundColor Cyan
    git push --dry-run origin ("HEAD:" + $branch) | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: GitHub push authentication preflight failed. Complete the browser sign-in once, then restart this sync." -ForegroundColor Red
        exit 13
    }
    Write-Host "GitHub push authentication preflight succeeded." -ForegroundColor Green

    $env:GCM_INTERACTIVE = "Never"
    $env:GIT_TERMINAL_PROMPT = "0"
} else {
    Write-Host "Git push disabled; summaries/diagnostics will only be generated locally." -ForegroundColor Yellow
}

python @argsList
