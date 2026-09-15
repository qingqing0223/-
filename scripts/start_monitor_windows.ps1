$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."
if (-not $env:DASHSCOPE_API_KEY) {
    Write-Host "ERROR: DASHSCOPE_API_KEY is not set." -ForegroundColor Red
    exit 1
}
python .\run_monitor.py --config .\config\monitoring.windows.json
