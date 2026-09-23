param(
    [string]$Config = ".\config\monitoring.local.json"
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
$MediaCrawlerRoot = [string]$cfg.media_crawler_root
if (-not $MediaCrawlerRoot -or -not (Test-Path (Join-Path $MediaCrawlerRoot "main.py"))) {
    Write-Host "ERROR: invalid media_crawler_root in $resolvedConfig : $MediaCrawlerRoot" -ForegroundColor Red
    exit 3
}

$keyword = "民族团结进步宣传周"
if ($cfg.keywords -and $cfg.keywords.Count -gt 0) {
    $keyword = [string]$cfg.keywords[0]
}

$stateRoot = Join-Path ([string]$cfg.data_root) "state\ks_login_bootstrap"
New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
$log = Join-Path $stateRoot ("bootstrap_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Write-Host ""
Write-Host "=== Kuaishou session bootstrap ===" -ForegroundColor Cyan
Write-Host "If the official Kuaishou login window/QR appears, complete it manually." -ForegroundColor Yellow
Write-Host "This step is OUTSIDE the five-minute acceptance clock." -ForegroundColor Yellow
Write-Host "No external 9222 browser is required." -ForegroundColor Green
Write-Host ""

$oldPublicMetrics = $env:KUAISHOU_PUBLIC_METRICS
$oldRealtime = $env:PROMOTION_WEEK_KS_REALTIME
$oldSlice = $env:PROMOTION_WEEK_KS_REALTIME_ITEMS_PER_KEYWORD
$env:KUAISHOU_PUBLIC_METRICS = ""
$env:PROMOTION_WEEK_KS_REALTIME = "1"
$env:PROMOTION_WEEK_KS_REALTIME_ITEMS_PER_KEYWORD = "1"

try {
    Push-Location $MediaCrawlerRoot
    & uv run main.py --platform ks --lt qrcode --type search --keywords $keyword --crawler_max_notes_count 20 --max_concurrency_num 1 --get_comment no --get_sub_comment no --save_data_option jsonl --save_data_path $stateRoot 2>&1 | Tee-Object -FilePath $log
    $rc = $LASTEXITCODE
    Pop-Location
} finally {
    $env:KUAISHOU_PUBLIC_METRICS = $oldPublicMetrics
    $env:PROMOTION_WEEK_KS_REALTIME = $oldRealtime
    $env:PROMOTION_WEEK_KS_REALTIME_ITEMS_PER_KEYWORD = $oldSlice
}

$logText = ""
if (Test-Path $log) {
    $logText = Get-Content $log -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
}

$explicitFailure = (
    $logText -match "Login kuaishou failed" -or
    $logText -match "login failed , have not found qrcode" -or
    $logText -match "manual login required" -or
    $logText -match "VERIFY_REQUIRED" -or
    $logText -match "captcha"
)

$crawlerFinished = $logText -match "Kuaishou Crawler finished"
$loginSucceeded = (
    $logText -match "Login successful" -or
    ($logText -notmatch "KUAISHOU_LOGIN_REQUIRED" -and $crawlerFinished)
)

if ($rc -ne 0 -or $explicitFailure -or -not $loginSucceeded) {
    Write-Host ""
    Write-Host "KUAISHOU SESSION BOOTSTRAP NOT VERIFIED." -ForegroundColor Red
    Write-Host "Complete the official login/security verification and rerun this bootstrap." -ForegroundColor Yellow
    Write-Host "Log: $log" -ForegroundColor Yellow
    exit 86
}

Write-Host ""
Write-Host "KUAISHOU SESSION BOOTSTRAP PASSED." -ForegroundColor Green
Write-Host "The saved browser profile can now be reused by the timed realtime cycle." -ForegroundColor Green
Write-Host "Log: $log" -ForegroundColor DarkGray
exit 0
