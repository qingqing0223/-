param(
    [string]$NodeId = "wechatmp01",
    [string]$Config = ".\config\monitoring.wechat.windows.json",
    [switch]$Start
)
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path "$PSScriptRoot\..").Path
$PythonExe = if (Test-Path ".\.venv\Scripts\python.exe") { (Resolve-Path ".\.venv\Scripts\python.exe").Path } else { (Get-Command python -ErrorAction Stop).Source }
& $PythonExe .\scripts\verify_wechat_mp_final.py --config $Config --config-only
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "WeChat MP V3: public collection and tables 1-5. No classification or repository operations."
if ($Start) {
    & .\scripts\start_wechat_platform_windows.ps1 -Platform wechat_mp -NodeId $NodeId -Config $Config
}
