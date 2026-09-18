param(
    [string]$NodeId = "bili-coordinator",
    [string]$Config = ".\config\monitoring.local.json"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

if (-not (Test-Path $Config)) {
    Write-Host "ERROR: config not found: $Config" -ForegroundColor Red
    exit 1
}

Write-Host "Publishing this coordinator/tester Bilibili result shard..." -ForegroundColor Cyan
Write-Host "NodeId: $NodeId" -ForegroundColor Cyan
Write-Host "Target: results/YYYY-MM-DD/nodes/bili/$NodeId.json" -ForegroundColor Green
Write-Host "GitHub Actions will rebuild results/YYYY-MM-DD/platforms/bili.json and overview.json." -ForegroundColor Green

python .\scripts\publish_node_result_to_github.py `
    --platform bili `
    --node-id $NodeId `
    --config $Config `
    --push

exit $LASTEXITCODE
