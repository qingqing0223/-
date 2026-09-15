param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","wb","ks")]
    [string]$Platform,

    [string]$Keyword = "男子停止资助学生后遭威胁"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $root

if (-not $env:DASHSCOPE_API_KEY) {
    Write-Host "ERROR: DASHSCOPE_API_KEY is not set." -ForegroundColor Red
    exit 1
}

Write-Host "Checking Suqi dashboard backend..." -ForegroundColor Cyan
python "$root\scripts\check_suqi_dashboard.py"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Dashboard backend is not running. Starting the latest Suqi dashboard..." -ForegroundColor Yellow
    & "$root\scripts\open_latest_dashboard_windows.ps1"
    Set-Location $root

    $ok = $false
    for ($i = 0; $i -lt 12; $i++) {
        Start-Sleep -Seconds 1
        python "$root\scripts\check_suqi_dashboard.py"
        if ($LASTEXITCODE -eq 0) {
            $ok = $true
            break
        }
    }
    if (-not $ok) {
        Write-Host "ERROR: Suqi dashboard backend still unavailable after startup attempt." -ForegroundColor Red
        exit 1
    }
}

Write-Host "Running one-shot full-chain hot-event test" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "Keyword:  $Keyword" -ForegroundColor Cyan

python "$root\run_single_platform.py" --platform $Platform --keyword $Keyword --once
