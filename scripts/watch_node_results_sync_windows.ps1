param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","toutiao","zhihu","wechat_mp","wechat_channels")]
    [string]$Platform,

    [string]$NodeId = $env:COMPUTERNAME,
    [string]$Config = ".\config\monitoring.student.windows.json",
    [int]$RestartDelaySeconds = 20
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

if (-not $NodeId) {
    $NodeId = "student-node"
}
if (-not (Test-Path $Config)) {
    Write-Host "ERROR: config not found: $Config" -ForegroundColor Red
    exit 1
}

Write-Host "=== GitHub result sync watchdog ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "NodeId:   $NodeId" -ForegroundColor Cyan
Write-Host "The sync publishes immediately, then every 300 seconds." -ForegroundColor Green
Write-Host "Concurrent remote updates are handled inside the publisher." -ForegroundColor Green

while ($true) {
    & .\scripts\start_node_results_sync_windows.ps1 `
        -Platform $Platform `
        -NodeId $NodeId `
        -Config $Config `
        -Push

    $exitCode = $LASTEXITCODE
    Write-Host "Result sync exited with code $exitCode." -ForegroundColor Yellow

    if ($exitCode -eq 12) {
        Write-Host "Sync stopped: repository is detached/not on a normal branch. Pull the latest main branch manually, then restart." -ForegroundColor Red
        exit $exitCode
    }
    if ($exitCode -eq 13) {
        Write-Host "Sync stopped: GitHub authentication/write access requires manual action. Complete browser sign-in, then restart." -ForegroundColor Red
        exit $exitCode
    }

    Write-Host "Transient sync failure detected; restarting in $RestartDelaySeconds seconds..." -ForegroundColor Yellow
    Start-Sleep -Seconds $RestartDelaySeconds
}
