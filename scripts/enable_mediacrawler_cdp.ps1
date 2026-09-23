param(
    [string]$Config = ".\config\monitoring.local.json",
    [string]$MediaCrawlerRoot = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

if (-not $MediaCrawlerRoot) {
    if (Test-Path $Config) {
        $resolvedConfig = (Resolve-Path $Config).Path
        $cfg = Get-Content $resolvedConfig -Raw -Encoding UTF8 | ConvertFrom-Json
        $MediaCrawlerRoot = [string]$cfg.media_crawler_root
    }
}

if (-not $MediaCrawlerRoot) {
    Write-Host "ERROR: MediaCrawler root is not configured. Use -MediaCrawlerRoot or a config containing media_crawler_root." -ForegroundColor Red
    exit 1
}

$target = Join-Path $MediaCrawlerRoot "config\base_config.py"
if (-not (Test-Path $target)) {
    Write-Host "ERROR: MediaCrawler config not found: $target" -ForegroundColor Red
    exit 1
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = "$target.bak_$timestamp"
Copy-Item $target $backup -Force

$text = [System.IO.File]::ReadAllText($target, [System.Text.Encoding]::UTF8)

# Kuaishou detail subprocesses must not depend on a browser already listening
# on 127.0.0.1:9222. MediaCrawler will launch its own CDP browser when
# CDP_CONNECT_EXISTING=False, and Kuaishou falls back to standard Playwright if
# CDP launch fails.
$changes = @{
    'HEADLESS' = 'False'
    'SAVE_LOGIN_STATE' = 'True'
    'ENABLE_CDP_MODE' = 'True'
    'CDP_HEADLESS' = 'False'
    'CDP_CONNECT_EXISTING' = 'False'
    'AUTO_CLOSE_BROWSER' = 'True'
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

Write-Host "MediaCrawler Kuaishou browser settings updated successfully." -ForegroundColor Green
Write-Host "MediaCrawler root: $MediaCrawlerRoot" -ForegroundColor Cyan
Write-Host "External 127.0.0.1:9222 browser is NOT required." -ForegroundColor Green
Write-Host "Backup: $backup" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Current settings:" -ForegroundColor Cyan
Select-String -Path $target -Pattern '^(HEADLESS|SAVE_LOGIN_STATE|ENABLE_CDP_MODE|CDP_HEADLESS|CDP_CONNECT_EXISTING|AUTO_CLOSE_BROWSER)\s*=' | ForEach-Object { $_.Line }
