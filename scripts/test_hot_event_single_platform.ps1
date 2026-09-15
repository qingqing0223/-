param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","wb","ks")]
    [string]$Platform,

    [string]$Keyword = "男子停止资助学生后遭威胁"
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

Write-Host "Running one-shot full-chain hot-event test" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "Keyword:  $Keyword" -ForegroundColor Cyan

python .\run_single_platform.py --platform $Platform --keyword $Keyword --once
