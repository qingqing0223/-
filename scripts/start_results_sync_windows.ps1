param(
    [int]$IntervalSeconds = 900,
    [switch]$Push
)

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

if ($IntervalSeconds -lt 300) {
    Write-Host "ERROR: IntervalSeconds must be >= 300." -ForegroundColor Red
    exit 1
}

Write-Host "Starting privacy-safe results sync." -ForegroundColor Cyan
Write-Host "Interval: $IntervalSeconds seconds" -ForegroundColor Cyan
Write-Host "Only aggregate files under results/ are generated; raw content is not committed." -ForegroundColor Yellow

$argsList = @(
    ".\scripts\publish_results_to_github.py",
    "--loop",
    "--interval", $IntervalSeconds
)
if ($Push) {
    $argsList += "--push"
    Write-Host "Git push is ENABLED and will use this computer's existing Git credentials." -ForegroundColor Yellow
} else {
    Write-Host "Git push is disabled; summaries will only be generated locally." -ForegroundColor Yellow
}

python @argsList
