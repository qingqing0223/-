param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","wb","ks","bili","toutiao","zhihu")]
    [string]$Platform,

    [string]$Config = ".\config\monitoring.local.json",
    [int]$RestartDelaySeconds = 60
)

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

if (-not (Test-Path $Config)) {
    Write-Host "ERROR: config not found: $Config" -ForegroundColor Red
    exit 1
}

$cfgObj = Get-Content $Config -Raw -Encoding UTF8 | ConvertFrom-Json
$baseRoot = [System.IO.DirectoryInfo]$cfgObj.data_root
$dataRoot = Join-Path $baseRoot.Parent.FullName ($baseRoot.Name + "_" + $Platform)
$statusPath = Join-Path $dataRoot "status\latest_status.json"

Write-Host "=== FINAL student platform watchdog ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "Config:   $Config" -ForegroundColor Cyan
Write-Host "Five-minute discovery + bounded deep-comment queue is enabled." -ForegroundColor Yellow
Write-Host "A failed/timeout detail candidate is isolated and partial JSONL is rolled back." -ForegroundColor Yellow
Write-Host "LOGIN_REQUIRED / VERIFY_REQUIRED stops automatic restart for manual official verification." -ForegroundColor Yellow
if (-not $env:DASHSCOPE_API_KEY) {
    Write-Host "DASHSCOPE_API_KEY is not set. Collection will continue; attitude classification will be degraded/unclassified." -ForegroundColor Yellow
}

while ($true) {
    python .\run_student_platform_final.py --platform $Platform --config $Config
    $exitCode = $LASTEXITCODE

    $state = "UNKNOWN"
    if (Test-Path $statusPath) {
        try {
            $status = Get-Content $statusPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($status.platform_runs -and $status.platform_runs.Count -gt 0) {
                $state = [string]$status.platform_runs[0].state
            }
        } catch {
            $state = "STATUS_READ_ERROR"
        }
    }

    Write-Host "Monitor exited. exitCode=$exitCode state=$state" -ForegroundColor Yellow

    if ($state -eq "VERIFY_REQUIRED" -or $state -eq "LOGIN_REQUIRED") {
        Write-Host "Automatic restart stopped. Complete the platform's official login/security verification manually, then restart this watchdog." -ForegroundColor Red
        exit 2
    }

    Write-Host "Restarting after $RestartDelaySeconds seconds... Press Ctrl+C to stop." -ForegroundColor Yellow
    Start-Sleep -Seconds $RestartDelaySeconds
}
