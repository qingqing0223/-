param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('xhs','dy','ks','bili','wb','toutiao','zhihu','wechat_mp','wechat_channels')]
    [string]$Platform,

    [string]$Config = '.\config\monitoring.local.json'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$env:PYTHONPATH = $repoRoot

Write-Host "Backfilling public region/IP-location labels..." -ForegroundColor Cyan
Write-Host "Platform: $Platform"
Write-Host "RepoRoot: $repoRoot"
Write-Host "Config: $Config"

python .\scripts\backfill_public_regions.py --platform $Platform --config $Config
if ($LASTEXITCODE -ne 0) {
    throw "Region backfill failed with exit code $LASTEXITCODE"
}
