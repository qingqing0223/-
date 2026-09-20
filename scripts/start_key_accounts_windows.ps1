param(
    [ValidateSet("xhs","dy","ks","bili","wb","zhihu")]
    [string]$Platform = ""
)

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

$config = ".\config\key_accounts.json"
if (-not (Test-Path $config)) {
    Write-Host "ERROR: $config does not exist." -ForegroundColor Red
    Write-Host "Copy .\config\key_accounts.example.json to key_accounts.json and fill verified creator IDs first." -ForegroundColor Yellow
    exit 1
}
if (-not $env:DASHSCOPE_API_KEY) {
    Write-Host "ERROR: DASHSCOPE_API_KEY is not set." -ForegroundColor Red
    exit 1
}

python .\scripts\check_suqi_dashboard.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($Platform) {
    python .\run_key_accounts.py --config $config --platform $Platform
} else {
    python .\run_key_accounts.py --config $config
}
