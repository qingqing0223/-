$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

Write-Host "This combined XHS + Douyin launcher is deprecated for the current deployment plan." -ForegroundColor Yellow
Write-Host "Run one platform per PowerShell instead:" -ForegroundColor Cyan
Write-Host "  .\scripts\start_single_platform_windows.ps1 -Platform xhs"
Write-Host "  .\scripts\start_single_platform_windows.ps1 -Platform dy"
Write-Host "  .\scripts\start_single_platform_windows.ps1 -Platform wb"
Write-Host "  .\scripts\start_single_platform_windows.ps1 -Platform ks"
exit 1
