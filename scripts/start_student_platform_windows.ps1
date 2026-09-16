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

# PowerShell 5.1 can turn stderr from a native executable into a terminating
# NativeCommandError when ErrorActionPreference=Stop. That prevented the intended
# self-repair from running when opinion_monitor_v2 was missing. Probe/install with
# native stderr treated as ordinary process output and decide from $LASTEXITCODE.
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $PythonExe -c "import opinion_monitor_v2" 2>$null
$importCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference

if ($importCode -ne 0) {
    Write-Host "Local classifier package is missing in the current Python; installing packages/v2..." -ForegroundColor Yellow

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $PythonExe -m pip install -e (Join-Path $RepoRoot "packages\v2")
    $installCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference

    if ($installCode -ne 0) {
        Write-Host "ERROR: failed to install local classifier package packages/v2." -ForegroundColor Red
        exit $installCode
    }

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $PythonExe -c "import opinion_monitor_v2; print('opinion_monitor_v2 import OK:', opinion_monitor_v2.__file__)"
    $verifyCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference

    if ($verifyCode -ne 0) {
        Write-Host "ERROR: classifier package still cannot be imported by $PythonExe." -ForegroundColor Red
        exit $verifyCode
    }
}

# Students created monitoring.local.json before the full capability matrix was
# enabled. Keep machine-specific paths/dashboard settings, but upgrade these local
# copies automatically so a git pull is enough to activate the new collection policy.
$resolvedConfig = (Resolve-Path $Config).Path
if ([System.IO.Path]::GetFileName($resolvedConfig) -like "*.local.json") {
    $cfgObj = Get-Content $resolvedConfig -Raw -Encoding UTF8 | ConvertFrom-Json
    function Set-ConfigProperty($obj, [string]$name, $value) {
        if ($obj.PSObject.Properties.Name -contains $name) {
            $obj.$name = $value
        } else {
            $obj | Add-Member -NotePropertyName $name -NotePropertyValue $value
        }
    }
    Set-ConfigProperty $cfgObj "search_until_exhausted" $true
    Set-ConfigProperty $cfgObj "crawler_max_notes_count" 100000
    Set-ConfigProperty $cfgObj "comments_until_exhausted" $true
    Set-ConfigProperty $cfgObj "max_comments_count_singlenotes" 100000
    Set-ConfigProperty $cfgObj "get_comment" "yes"
    Set-ConfigProperty $cfgObj "get_sub_comment" "yes"
    Set-ConfigProperty $cfgObj "ingest_comments" $true
    Set-ConfigProperty $cfgObj "max_concurrency_num" 1
    $json = $cfgObj | ConvertTo-Json -Depth 100
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($resolvedConfig, $json, $utf8NoBom)
    Write-Host "Local config upgraded: full paging + first-level comments + nested comments + comment ingestion enabled." -ForegroundColor Green
}

Write-Host "=== Student distributed platform monitor ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "NodeId:   $NodeId" -ForegroundColor Cyan
Write-Host "Config:   $Config" -ForegroundColor Cyan
Write-Host "Full matrix mode: search to natural end (100000 safety cap), comments and sub-comments enabled." -ForegroundColor Yellow
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
