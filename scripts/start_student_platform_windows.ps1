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

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "ERROR: python was not found in this PowerShell session." -ForegroundColor Red
    exit 1
}
$PythonExe = $pythonCmd.Source
Write-Host "Python:   $PythonExe" -ForegroundColor Cyan

# The classifier is a local package in packages/v2. Student setup normally installs
# it through requirements.txt, but a network failure while cloning MediaCrawler can
# stop setup before that step. Repair it automatically here instead of asking students
# to guess a pip command.
& $PythonExe -c "import opinion_monitor_v2" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Local classifier package is missing in the current Python; installing packages/v2..." -ForegroundColor Yellow
    & $PythonExe -m pip install -e (Join-Path $RepoRoot "packages\v2")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: failed to install local classifier package packages/v2." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    & $PythonExe -c "import opinion_monitor_v2; print('opinion_monitor_v2 import OK:', opinion_monitor_v2.__file__)"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: classifier package still cannot be imported by $PythonExe." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Write-Host "=== Student distributed platform monitor ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "NodeId:   $NodeId" -ForegroundColor Cyan
Write-Host "Config:   $Config" -ForegroundColor Cyan
Write-Host "Dashboard is disabled on student machines; classified aggregate results can sync to GitHub." -ForegroundColor Yellow

if ($PushGithub) {
    $syncCmd = "Set-Location '$RepoRoot'; .\scripts\start_node_results_sync_windows.ps1 -Platform $Platform -NodeId '$NodeId' -Config '$Config' -Push"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $syncCmd
    Write-Host "GitHub aggregate shard sync started in a separate window." -ForegroundColor Green
} else {
    Write-Host "GitHub push is OFF. Add -PushGithub after this machine has Git write access." -ForegroundColor Yellow
}

if ($NoWatchdog) {
    & $PythonExe .\run_single_platform.py --platform $Platform --config $Config
} else {
    .\scripts\watch_single_platform_windows.ps1 -Platform $Platform -Config $Config
}
