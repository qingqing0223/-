param(
    [string]$Config = ".\config\monitoring.local.json",
    [int]$RestartDelaySeconds = 20
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

Write-Host "=== Bilibili coordinator automatic GitHub sync ===" -ForegroundColor Cyan
Write-Host "NodeId: bili-coordinator" -ForegroundColor Cyan
Write-Host "Config: $Config" -ForegroundColor Cyan
Write-Host "Publishes immediately, then every 300 seconds." -ForegroundColor Green
Write-Host "Keep this PowerShell window open while the coordinator is collecting." -ForegroundColor Yellow

& .\scripts\watch_node_results_sync_windows.ps1 `
    -Platform bili `
    -NodeId bili-coordinator `
    -Config $Config `
    -RestartDelaySeconds $RestartDelaySeconds

exit $LASTEXITCODE
