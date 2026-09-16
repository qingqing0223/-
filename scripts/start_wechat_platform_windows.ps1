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
    Set-ConfigProperty $cfgObj "wechat_mp_search_until_exhausted" $true
    Set-ConfigProperty $cfgObj "wechat_mp_max_pages" 1000
    Set-ConfigProperty $cfgObj "wechat_mp_max_results_per_keyword" 100000
    Set-ConfigProperty $cfgObj "wechat_channels_scroll_pages" 1000
    Set-ConfigProperty $cfgObj "wechat_channels_max_results_per_keyword" 100000
    if ($Platform -eq "wechat_mp") {
        Set-ConfigProperty $cfgObj "interval_seconds" 300
        Set-ConfigProperty $cfgObj "wechat_mp_interval_seconds" 300
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
    Write-Host "WeChat local config upgraded for realtime/deep paging." -ForegroundColor Green
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
