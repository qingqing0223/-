$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

Write-Host "=== Android WeChat Channels setup ===" -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Python not found." -ForegroundColor Red
    exit 1
}

$adb = Get-Command adb -ErrorAction SilentlyContinue
if (-not $adb) {
    Write-Host "ADB_NOT_FOUND" -ForegroundColor Yellow
    Write-Host "Install Google's official Android SDK Platform-Tools for Windows, then reopen PowerShell." -ForegroundColor Yellow
    Write-Host "Official page: https://developer.android.com/tools/releases/platform-tools" -ForegroundColor Yellow
    Write-Host "After extracting, add the platform-tools folder to PATH, then run: adb devices" -ForegroundColor Yellow
    exit 2
}

Write-Host "ADB: $($adb.Source)" -ForegroundColor Green
Write-Host "Installing/updating uiautomator2..." -ForegroundColor Cyan
python -m pip install -U uiautomator2
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "" 
Write-Host "Connected Android devices:" -ForegroundColor Cyan
adb devices -l
Write-Host ""
Write-Host "On the phone, accept the USB debugging/RSA authorization prompt and keep the phone unlocked." -ForegroundColor Yellow
Write-Host "Then open WeChat -> Channels and run:" -ForegroundColor Yellow
Write-Host "python .\scripts\diagnose_channels_android.py" -ForegroundColor Cyan
