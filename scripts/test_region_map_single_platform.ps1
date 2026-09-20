param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","toutiao","zhihu")]
    [string]$Platform,

    [string]$Keyword = "民族团结"
)

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

if (-not $env:DASHSCOPE_API_KEY) {
    Write-Host "ERROR: DASHSCOPE_API_KEY is not set." -ForegroundColor Red
    exit 1
}

Write-Host "Checking Suqi dashboard backend..." -ForegroundColor Cyan
python .\scripts\check_suqi_dashboard.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Running region-enrichment test" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "Keyword:  $Keyword" -ForegroundColor Cyan
Write-Host "This profile collects a bounded sample of first-level comments (max 5 per item) so public province/IP-location labels, when the platform returns them, can update the map." -ForegroundColor Yellow
Write-Host "No raw IP address is required or stored by this integration." -ForegroundColor Yellow

python .\run_single_platform.py `
  --platform $Platform `
  --config .\config\monitoring.region.windows.json `
  --keyword $Keyword `
  --once

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Check the JSON result above:" -ForegroundColor Cyan
Write-Host "  region_records > 0  => this batch contained usable public region labels" -ForegroundColor Green
Write-Host "  region_rate         => share of classified records with region" -ForegroundColor Green
Write-Host "A zero region rate can simply mean the current MediaCrawler export does not expose a public region label for this platform/build." -ForegroundColor Yellow
Write-Host "Then refresh/open http://127.0.0.1:8765/ and watch province counts on the China map." -ForegroundColor Green
