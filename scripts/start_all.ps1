param(
    [ValidateSet("xhs","dy","wb","ks","bili","toutiao","zhihu")]
    [string]$Platform = "ks",

    [string]$Config = "",
    [string]$DashboardRoot = "E:\Real-time-situation-map\yuqing-v1\03_live_system",
    [switch]$Multilingual,
    [switch]$EnableGithubSync,
    [switch]$PushGithub,
    [switch]$EnableKeyAccounts,
    [switch]$PullLatest,
    [switch]$NoWatchdog,
    [switch]$SkipPreflight
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path "$PSScriptRoot\.."
Set-Location $RepoRoot

if ($PullLatest) {
    Write-Host "Updating integration repository with git pull --ff-only..." -ForegroundColor Cyan
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        Write-Host "git pull failed. Resolve local Git changes before continuing." -ForegroundColor Red
        exit 1
    }
}

if (-not $Config) {
    if ($Multilingual) {
        $Config = ".\config\monitoring.multilingual.windows.json"
    } else {
        $Config = ".\config\monitoring.windows.json"
    }
}

if (-not (Test-Path $Config)) {
    Write-Host "ERROR: config not found: $Config" -ForegroundColor Red
    exit 1
}
if (-not $env:DASHSCOPE_API_KEY) {
    Write-Host "ERROR: DASHSCOPE_API_KEY is not set." -ForegroundColor Red
    exit 1
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: python is not available in PATH." -ForegroundColor Red
    exit 1
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "WARNING: uv is not available in this shell; MediaCrawler requires it." -ForegroundColor Yellow
}

Write-Host "=== Realtime Opinion Monitor ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "Config:   $Config" -ForegroundColor Cyan

if (-not $SkipPreflight) {
    Write-Host "Running deployment preflight..." -ForegroundColor Cyan
    python .\scripts\preflight.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Preflight has required failures. Fix them before deployment." -ForegroundColor Red
        exit 1
    }
}

python .\scripts\check_suqi_dashboard.py *> $null
if ($LASTEXITCODE -ne 0) {
    if (-not (Test-Path (Join-Path $DashboardRoot "server.py"))) {
        Write-Host "ERROR: Suqi server.py not found under $DashboardRoot" -ForegroundColor Red
        exit 1
    }
    Write-Host "Suqi backend is not running; starting it..." -ForegroundColor Yellow
    $serverCmd = "Set-Location '$DashboardRoot'; python .\server.py --no-sim"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $serverCmd

    $ready = $false
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        python .\scripts\check_suqi_dashboard.py *> $null
        if ($LASTEXITCODE -eq 0) {
            $ready = $true
            break
        }
    }
    if (-not $ready) {
        Write-Host "ERROR: Suqi backend did not become healthy within 20 seconds." -ForegroundColor Red
        exit 1
    }
}
Write-Host "Suqi backend: OK" -ForegroundColor Green

Start-Process "http://127.0.0.1:8765/"

if ($EnableGithubSync) {
    $syncArgs = "-IntervalSeconds 900"
    if ($PushGithub) { $syncArgs += " -Push" }
    $syncCmd = "Set-Location '$RepoRoot'; .\scripts\start_results_sync_windows.ps1 $syncArgs"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $syncCmd
    Write-Host "Aggregate results sync: started" -ForegroundColor Green
    if (-not $PushGithub) {
        Write-Host "Git push is OFF. Add -PushGithub after local Git credentials are verified." -ForegroundColor Yellow
    }
}

if ($EnableKeyAccounts) {
    if (Test-Path ".\config\key_accounts.json") {
        $keyCmd = "Set-Location '$RepoRoot'; .\scripts\start_key_accounts_windows.ps1 -Platform $Platform"
        Start-Process powershell -ArgumentList "-NoExit", "-Command", $keyCmd
        Write-Host "Key-account monitor: started for $Platform" -ForegroundColor Green
    } else {
        Write-Host "Key-account monitor not started: config\key_accounts.json is missing." -ForegroundColor Yellow
        Write-Host "Copy config\key_accounts.example.json and fill verified creator IDs first." -ForegroundColor Yellow
    }
}

if ($NoWatchdog) {
    Write-Host "Starting monitor without watchdog..." -ForegroundColor Cyan
    .\scripts\start_single_platform_windows.ps1 -Platform $Platform -Config $Config
} else {
    Write-Host "Starting monitor with safe watchdog..." -ForegroundColor Cyan
    .\scripts\watch_single_platform_windows.ps1 -Platform $Platform -Config $Config
}
