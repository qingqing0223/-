param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","toutiao","zhihu")]
    [string]$Platform,

    [string]$Config = ".\\config\\monitoring.local.json"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\\..").Path
Set-Location $RepoRoot

Write-Host "=== Public IP-region acceptance check ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "This checks only platform-displayed coarse region labels; real IPs/precise location are never used." -ForegroundColor Yellow

python .\\scripts\\inspect_public_region_acceptance.py --platform $Platform --config $Config
exit $LASTEXITCODE
