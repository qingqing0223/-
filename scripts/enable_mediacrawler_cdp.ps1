$ErrorActionPreference = "Stop"

$target = "E:\MediaCrawler_clean\config\base_config.py"

if (-not (Test-Path $target)) {
    Write-Host "ERROR: MediaCrawler config not found: $target" -ForegroundColor Red
    exit 1
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = "$target.bak_$timestamp"
Copy-Item $target $backup -Force

$text = [System.IO.File]::ReadAllText($target, [System.Text.Encoding]::UTF8)

$changes = @{
    'HEADLESS' = 'False'
    'SAVE_LOGIN_STATE' = 'True'
    'ENABLE_CDP_MODE' = 'True'
    'CDP_HEADLESS' = 'False'
    'CDP_CONNECT_EXISTING' = 'False'
    'AUTO_CLOSE_BROWSER' = 'False'
}

foreach ($name in $changes.Keys) {
    $pattern = "(?m)^\s*" + [regex]::Escape($name) + "\s*=\s*.*$"
    if (-not [regex]::IsMatch($text, $pattern)) {
        Write-Host "ERROR: setting not found in base_config.py: $name" -ForegroundColor Red
        Write-Host "Backup kept at: $backup" -ForegroundColor Yellow
        exit 1
    }
    $replacement = "$name = $($changes[$name])"
    $text = [regex]::Replace($text, $pattern, $replacement)
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($target, $text, $utf8NoBom)

Write-Host "MediaCrawler CDP settings updated successfully." -ForegroundColor Green
Write-Host "Backup: $backup" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Current settings:" -ForegroundColor Cyan
Select-String -Path $target -Pattern '^(HEADLESS|SAVE_LOGIN_STATE|ENABLE_CDP_MODE|CDP_HEADLESS|CDP_CONNECT_EXISTING|AUTO_CLOSE_BROWSER)\s*=' | ForEach-Object { $_.Line }
