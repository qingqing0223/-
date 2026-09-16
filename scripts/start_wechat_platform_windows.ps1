param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("wechat_mp","wechat_channels")]
    [string]$Platform,

    [string]$NodeId = $env:COMPUTERNAME,
    [string]$Config = ".\config\monitoring.wechat.local.json",
    [switch]$PushGithub,
    [switch]$Once
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

if (-not $env:DASHSCOPE_API_KEY) {
    Write-Host "ERROR: DASHSCOPE_API_KEY is not set in this PowerShell session." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $Config)) {
    Write-Host "ERROR: config not found: $Config" -ForegroundColor Red
    Write-Host "Run .\scripts\setup_wechat_windows.ps1 first." -ForegroundColor Yellow
    exit 1
}
if (-not $NodeId) {
    $NodeId = "$Platform-node"
}

if ($Platform -eq "wechat_channels") {
    $wechatProc = Get-Process -Name Weixin,WeChat -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $wechatProc) {
        Write-Host "ERROR: WeChat desktop is not running." -ForegroundColor Red
        Write-Host "Open the official WeChat Windows client, log in normally, then rerun." -ForegroundColor Yellow
        exit 1
    }
}

Write-Host "=== WeChat monitoring ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "NodeId:   $NodeId" -ForegroundColor Cyan
Write-Host "Config:   $Config" -ForegroundColor Cyan
Write-Host "Official login/verification must be completed manually when requested." -ForegroundColor Yellow

if ($PushGithub) {
    $syncCmd = "Set-Location '$RepoRoot'; .\scripts\start_node_results_sync_windows.ps1 -Platform $Platform -NodeId '$NodeId' -Config '$Config' -Push"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $syncCmd
    Write-Host "GitHub aggregate sync started in a separate PowerShell window." -ForegroundColor Green
}

$argsList = @(".\run_wechat_platform.py", "--platform", $Platform, "--config", $Config)
if ($Once) {
    $argsList += "--once"
}
python @argsList
