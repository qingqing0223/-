param(
    [string]$NodeId = "wechatmp01",
    [string]$Config = ".\config\monitoring.wechat.local.json",
    [switch]$Start
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

Write-Host "=== FINAL WeChat MP monitoring upgrade ===" -ForegroundColor Cyan
Write-Host "NodeId: $NodeId" -ForegroundColor Cyan
Write-Host "Config: $Config" -ForegroundColor Cyan
Write-Host ""
Write-Host "Close any old WeChat MP collector/GitHub-sync windows before continuing." -ForegroundColor Yellow

try {
    $running = Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.CommandLine -and (
            $_.CommandLine -match "run_wechat_platform.py" -or
            $_.CommandLine -match "publish_node_result_to_github.py.*wechat_mp"
        )
    }
    if ($running) {
        Write-Host "ERROR: old WeChat MP monitoring/sync processes are still running." -ForegroundColor Red
        $running | Select-Object ProcessId, Name, CommandLine | Format-Table -AutoSize
        Write-Host "Close those old windows and rerun this command." -ForegroundColor Yellow
        exit 2
    }
} catch {
    Write-Host "Warning: process check unavailable; continuing." -ForegroundColor Yellow
}

if (-not $env:DASHSCOPE_API_KEY) {
    Write-Host "ERROR: DASHSCOPE_API_KEY is not set in this PowerShell session." -ForegroundColor Red
    exit 3
}

# Preserve current Git state before aligning to the final main branch.
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = "backup-final-wechat-mp-$stamp"
$head = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -eq 0 -and $head) {
    git branch $backup $head 2>$null
}
$gitDir = (git rev-parse --git-dir).Trim()
if ($LASTEXITCODE -eq 0 -and $gitDir) {
    if ((Test-Path (Join-Path $gitDir "rebase-merge")) -or (Test-Path (Join-Path $gitDir "rebase-apply"))) {
        git rebase --abort
    }
}

git stash push -u -m "final-wechat-mp-upgrade-$stamp" | Out-Host
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git fetch origin | Out-Host
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git switch -C main origin/main | Out-Host
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Repository aligned with origin/main. Backup branch: $backup" -ForegroundColor Green

if (-not (Test-Path $Config)) {
    Write-Host "Local WeChat config missing; creating it from the final template." -ForegroundColor Yellow
    .\scripts\setup_wechat_windows.ps1 -LocalConfig $Config
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    # Refresh Python integration dependencies without replacing the existing local config.
    $pythonCmd = Get-Command python -ErrorAction Stop
    $PythonExe = $pythonCmd.Source
    & $PythonExe -m pip install -r .\requirements.txt
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $PythonExe -m pip install "playwright>=1.50"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# The launcher itself upgrades old local configs to the final WeChat MP profile.
Write-Host "Running one configuration/collector verification pass..." -ForegroundColor Cyan
python .\scripts\verify_wechat_mp_final.py --config $Config --config-only
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: WeChat MP final verification failed. Send the JSON result to the coordinator." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "FINAL WeChat MP upgrade completed." -ForegroundColor Green
Write-Host "Final scope:" -ForegroundColor Cyan
Write-Host "  - six campaign keywords" -ForegroundColor Yellow
Write-Host "  - public Sogou-Weixin article search" -ForegroundColor Yellow
Write-Host "  - pagination to natural end with safety caps" -ForegroundColor Yellow
Write-Host "  - five-minute polling, time filtering, dedupe" -ForegroundColor Yellow
Write-Host "  - article attitude + v2 subtype + source type + language" -ForegroundColor Yellow
Write-Host "  - public publisher account aggregate statistics" -ForegroundColor Yellow
Write-Host "  - dashboard push + outbox + GitHub aggregate sync" -ForegroundColor Yellow
Write-Host "  - manual handling only for official CAPTCHA/security verification" -ForegroundColor Yellow
Write-Host "Known source limitations: public Sogou search does not expose full article comments/thread replies, public IP-region labels, or complete reliable engagement metrics." -ForegroundColor Yellow

if ($Start) {
    .\scripts\start_wechat_platform_windows.ps1 -Platform wechat_mp -NodeId $NodeId -Config $Config -PushGithub
} else {
    Write-Host "Start command:" -ForegroundColor Cyan
    Write-Host ".\scripts\start_wechat_platform_windows.ps1 -Platform wechat_mp -NodeId $NodeId -Config $Config -PushGithub" -ForegroundColor Green
}
