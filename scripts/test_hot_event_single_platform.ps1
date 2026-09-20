param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","toutiao","zhihu")]
    [string]$Platform,

    [string]$Keyword = ""
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $root

# Windows PowerShell 5.1 may misread UTF-8 scripts without BOM. Keep this file
# ASCII-only and construct the default Chinese test keyword from Unicode codepoints.
if ([string]::IsNullOrWhiteSpace($Keyword)) {
    $Keyword = -join @(
        [char]0x7537, [char]0x5B50, [char]0x505C, [char]0x6B62,
        [char]0x8D44, [char]0x52A9, [char]0x5B66, [char]0x751F,
        [char]0x540E, [char]0x906D, [char]0x5A01, [char]0x80C1
    )
}

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
Write-Host "If the platform opens an official CAPTCHA/verification page, finish it manually. Do not repeatedly rerun while verification is pending." -ForegroundColor Yellow

python "$root\run_single_platform.py" --platform $Platform --keyword $Keyword --once
