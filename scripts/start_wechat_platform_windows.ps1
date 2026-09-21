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

if ($Platform -eq "wechat_mp") {
    if (-not $PSBoundParameters.ContainsKey("NodeId")) { $NodeId = "wechatmp01" }
    if ($PushGithub) { throw "WeChat MP V3 collection does not support automatic GitHub publishing." }
    if (-not (Test-Path $Config)) { $Config = ".\config\monitoring.wechat.windows.json" }
    $PythonExe = if (Test-Path ".\.venv\Scripts\python.exe") { (Resolve-Path ".\.venv\Scripts\python.exe").Path } else { (Get-Command python -ErrorAction Stop).Source }
    $env:PYTHONIOENCODING = "utf-8"
    $mpArgs = @(".\run_wechat_platform.py", "--platform", "wechat_mp", "--config", $Config, "--node-id", $NodeId)
    if ($Once) { $mpArgs += "--once" }
    & $PythonExe @mpArgs
    exit $LASTEXITCODE
}

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

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "ERROR: python was not found in this PowerShell session." -ForegroundColor Red
    exit 1
}
$PythonExe = $pythonCmd.Source
Write-Host "Python:   $PythonExe" -ForegroundColor Cyan

# Make the v2 classifier self-repair in the active Python environment.
$oldEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $PythonExe -c "import opinion_monitor_v2" 2>$null
$importCode = $LASTEXITCODE
$ErrorActionPreference = $oldEap
if ($importCode -ne 0) {
    Write-Host "Local classifier package missing; installing packages/v2..." -ForegroundColor Yellow
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $PythonExe -m pip install -e (Join-Path $RepoRoot "packages\v2")
    $installCode = $LASTEXITCODE
    $ErrorActionPreference = $oldEap
    if ($installCode -ne 0) {
        Write-Host "ERROR: failed to install opinion_monitor_v2." -ForegroundColor Red
        exit $installCode
    }
}

# Upgrade existing per-machine WeChat local configs without replacing machine paths.
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
    Set-ConfigProperty $cfgObj "interval_seconds" 300
    Set-ConfigProperty $cfgObj "wechat_mp_interval_seconds" 300
    Set-ConfigProperty $cfgObj "wechat_mp_search_until_exhausted" $true
    Set-ConfigProperty $cfgObj "wechat_mp_max_pages" 1000
    Set-ConfigProperty $cfgObj "wechat_mp_max_results_per_keyword" 100000
    Set-ConfigProperty $cfgObj "wechat_channels_scroll_pages" 1000
    Set-ConfigProperty $cfgObj "wechat_channels_max_results_per_keyword" 100000
    Set-ConfigProperty $cfgObj "wechat_mp_source" "sogou_weixin_public_search"
    Set-ConfigProperty $cfgObj "wechat_mp_collect_public_articles" $true
    Set-ConfigProperty $cfgObj "wechat_mp_collect_comments" $false
    Set-ConfigProperty $cfgObj "wechat_mp_collect_public_ip_region" $false
    Set-ConfigProperty $cfgObj "wechat_mp_collect_reliable_engagement" $false
    if ($Platform -eq "wechat_mp") {
        $dashboardObj = [PSCustomObject]@{
            enabled = $true
            ingest_url = "http://127.0.0.1:8765/api/ingest"
            timeout_seconds = 15
        }
        Set-ConfigProperty $cfgObj "dashboard" $dashboardObj
    }
    $json = $cfgObj | ConvertTo-Json -Depth 100
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($resolvedConfig, $json, $utf8NoBom)
    Write-Host "WeChat local config upgraded to final realtime profile." -ForegroundColor Green
}

if ($Platform -eq "wechat_channels") {
    $wechatProc = Get-Process -Name Weixin,WeChat -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $wechatProc) {
        Write-Host "ERROR: WeChat desktop is not running." -ForegroundColor Red
        Write-Host "Open the official WeChat Windows client, log in normally, then rerun." -ForegroundColor Yellow
        exit 1
    }
}

Write-Host "=== WeChat monitoring FINAL profile ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "NodeId:   $NodeId" -ForegroundColor Cyan
Write-Host "Config:   $Config" -ForegroundColor Cyan
Write-Host "Official login/verification must be completed manually when requested." -ForegroundColor Yellow
if ($Platform -eq "wechat_mp") {
    Write-Host "WeChat MP scope: public article search -> paging -> dedupe -> time filter -> v2 attitude/source/language -> public account aggregate -> dashboard/GitHub." -ForegroundColor Yellow
    Write-Host "Important limitation: the public Sogou-Weixin search source does NOT expose full Selected Comments/thread replies, public IP-region labels, or reliable complete engagement metrics. These are reported as unavailable, not as zero evidence." -ForegroundColor Yellow
}

if ($PushGithub) {
    $syncCmd = "Set-Location '$RepoRoot'; .\scripts\start_node_results_sync_windows.ps1 -Platform $Platform -NodeId '$NodeId' -Config '$Config' -Push"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $syncCmd
    Write-Host "GitHub aggregate sync started in a separate PowerShell window." -ForegroundColor Green
}

$argsList = @(".\run_wechat_platform.py", "--platform", $Platform, "--config", $Config)
if ($Once) {
    $argsList += "--once"
}
& $PythonExe @argsList
