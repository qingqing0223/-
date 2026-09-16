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

if ($IntervalSeconds -lt 300) {
    Write-Host "ERROR: IntervalSeconds must be >= 300." -ForegroundColor Red
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
Write-Host "Interval: $IntervalSeconds seconds" -ForegroundColor Cyan
Write-Host "GitHub receives aggregate monitoring JSON: counts, attitude, comments/replies, public IP-region labels when exposed, engagement, language, video-analysis completeness, and public publisher account aggregate statistics. Raw post/comment text and URLs are not published." -ForegroundColor Yellow

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
} else {
    Write-Host "Git push disabled; summaries will only be generated locally." -ForegroundColor Yellow
}

python @argsList
