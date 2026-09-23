param(
    [string]$Config = ".\config\monitoring.local.json",
    [string]$MediaCrawlerRoot = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

if (-not (Test-Path $Config)) {
    Write-Host "ERROR: config not found: $Config" -ForegroundColor Red
    exit 2
}

$resolvedConfig = (Resolve-Path $Config).Path
$cfg = Get-Content $resolvedConfig -Raw -Encoding UTF8 | ConvertFrom-Json

if (-not $MediaCrawlerRoot) {
    $MediaCrawlerRoot = [string]$cfg.media_crawler_root
}
if (-not $MediaCrawlerRoot -or -not (Test-Path (Join-Path $MediaCrawlerRoot "main.py"))) {
    Write-Host "ERROR: invalid media_crawler_root: $MediaCrawlerRoot" -ForegroundColor Red
    exit 3
}

if (-not $cfg.keywords -or $cfg.keywords.Count -lt 1) {
    Write-Host "ERROR: config has no keywords." -ForegroundColor Red
    exit 4
}
$keyword = [string]$cfg.keywords[0]

$baseConfig = Join-Path $MediaCrawlerRoot "config\base_config.py"
if (-not (Test-Path $baseConfig)) {
    Write-Host "ERROR: MediaCrawler base_config.py not found: $baseConfig" -ForegroundColor Red
    exit 5
}

$text = [System.IO.File]::ReadAllText($baseConfig, [System.Text.Encoding]::UTF8)
$settings = @{
    "HEADLESS" = "False"
    "SAVE_LOGIN_STATE" = "True"
    "ENABLE_CDP_MODE" = "False"
}
foreach ($name in $settings.Keys) {
    $pattern = "(?m)^\s*" + [regex]::Escape($name) + "\s*=\s*.*$"
    if (-not [regex]::IsMatch($text, $pattern)) {
        Write-Host "ERROR: MediaCrawler setting missing: $name" -ForegroundColor Red
        exit 6
    }
    $text = [regex]::Replace($text, $pattern, "$name = $($settings[$name])")
}
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($baseConfig, $text, $utf8NoBom)

$stateRoot = Join-Path ([string]$cfg.data_root) "state\bili_login_bootstrap"
New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
$log = Join-Path $stateRoot ("bootstrap_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Write-Host ""
Write-Host "=== Bilibili session bootstrap ===" -ForegroundColor Cyan
Write-Host "This login step is OUTSIDE the five-minute realtime acceptance clock." -ForegroundColor Yellow
Write-Host "A visible Bilibili browser should open." -ForegroundColor Yellow
Write-Host "Complete the official QR/login/security verification manually if requested." -ForegroundColor Yellow
Write-Host "The browser will wait up to 600 seconds for the official session." -ForegroundColor Yellow
Write-Host ""

$oldBootstrap = $env:PROMOTION_WEEK_BILI_LOGIN_BOOTSTRAP
$env:PROMOTION_WEEK_BILI_LOGIN_BOOTSTRAP = "1"

$oldErrorActionPreference = $ErrorActionPreference
$rc = 1
try {
    Push-Location $MediaCrawlerRoot
    try {
        $ErrorActionPreference = "Continue"
        & uv run main.py --platform bili --lt qrcode --type search --keywords $keyword --crawler_max_notes_count 20 --max_concurrency_num 1 --get_comment no --get_sub_comment no --save_data_option jsonl --save_data_path $stateRoot 2>&1 | Tee-Object -FilePath $log
        $rc = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
        Pop-Location
    }
} finally {
    $env:PROMOTION_WEEK_BILI_LOGIN_BOOTSTRAP = $oldBootstrap
}

$logText = ""
if (Test-Path $log) {
    $logText = Get-Content $log -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
}

$verified = $logText -match "BILIBILI_SESSION_BOOTSTRAP_OK"
$timedOut = $logText -match "manual official login timed out"
$required = $logText -match "BILIBILI_LOGIN_REQUIRED"

if ($rc -ne 0 -or -not $verified) {
    Write-Host ""
    Write-Host "BILIBILI SESSION BOOTSTRAP NOT VERIFIED." -ForegroundColor Red
    if ($timedOut -or $required) {
        Write-Host "Complete the official login/security verification in the visible Bilibili browser, then rerun this bootstrap." -ForegroundColor Yellow
    } else {
        Write-Host "Inspect the bootstrap log before starting timed collection." -ForegroundColor Yellow
    }
    Write-Host "Log: $log" -ForegroundColor Yellow
    exit 86
}

Write-Host ""
Write-Host "BILIBILI SESSION BOOTSTRAP PASSED." -ForegroundColor Green
Write-Host "The persistent Bilibili browser profile is now ready for timed collection." -ForegroundColor Green
Write-Host "Log: $log" -ForegroundColor DarkGray
exit 0
