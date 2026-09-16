param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","tieba","zhihu")]
    [string]$Platform,

    [string]$NodeId = $env:COMPUTERNAME,
    [string]$Config = ".\config\monitoring.student.windows.json",
    [switch]$PushGithub,
    [switch]$NoWatchdog
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
    exit 1
}
if (-not $NodeId) {
    $NodeId = "student-node"
}

Write-Host "=== Student distributed platform monitor ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "NodeId:   $NodeId" -ForegroundColor Cyan
Write-Host "Dashboard is disabled on student machines; classified aggregate results can sync to GitHub." -ForegroundColor Yellow

if ($PushGithub) {
    $syncCmd = "Set-Location '$RepoRoot'; .\scripts\start_node_results_sync_windows.ps1 -Platform $Platform -NodeId '$NodeId' -Push"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $syncCmd
    Write-Host "GitHub aggregate shard sync started in a separate window." -ForegroundColor Green
} else {
    Write-Host "GitHub push is OFF. Add -PushGithub after this machine has Git write access." -ForegroundColor Yellow
}

if ($NoWatchdog) {
    python .\run_single_platform.py --platform $Platform --config $Config
} else {
    .\scripts\watch_single_platform_windows.ps1 -Platform $Platform -Config $Config
}
