param(
    [string]$PyWechatRoot = "",
    [string]$LocalConfig = ".\config\monitoring.wechat.local.json",
    [ValidateSet("wechat_mp", "wechat_channels", "all")]
    [string]$Platform = "all"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

if ($Platform -eq "wechat_mp") {
    $PythonExe = if (Test-Path ".\.venv\Scripts\python.exe") { (Resolve-Path ".\.venv\Scripts\python.exe").Path } else { (Get-Command python -ErrorAction Stop).Source }
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        uv pip install --python $PythonExe -r .\requirements-wechat-mp.txt
    } else {
        & $PythonExe -m pip install -r .\requirements-wechat-mp.txt
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if (-not (Test-Path $LocalConfig)) {
        Copy-Item -LiteralPath ".\config\monitoring.wechat.windows.json" -Destination $LocalConfig
    }
    Write-Host "WeChat MP collection setup completed. Chrome and Node.js with @oai/artifact-tool are required."
    Write-Host "No API key or classifier is needed. Complete official verification manually when prompted."
    exit 0
}

$drive = Split-Path -Qualifier $RepoRoot
if (-not $drive) {
    $drive = if (Test-Path "E:\") { "E:" } elseif (Test-Path "D:\") { "D:" } else { "C:" }
}
if (-not $PyWechatRoot) {
    $PyWechatRoot = "$drive\pywechat_rpa"
}
$dataRoot = "$drive\MediaCrawlerData\2026-09-16_promotion_week"

foreach ($cmd in @("git", "python")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "ERROR: required command not found: $cmd" -ForegroundColor Red
        exit 1
    }
}

Write-Host "=== WeChat automation setup ===" -ForegroundColor Cyan
Write-Host "Repo:       $RepoRoot" -ForegroundColor Cyan
Write-Host "pywechat:   $PyWechatRoot" -ForegroundColor Cyan
Write-Host "Data root:  $dataRoot" -ForegroundColor Cyan

Write-Host "Installing integration and WeChat-browser dependencies..." -ForegroundColor Cyan
python -m pip install -r .\requirements.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m pip install "playwright>=1.50"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not (Test-Path "$PyWechatRoot\src\pyweixin")) {
    if (Test-Path $PyWechatRoot) {
        Write-Host "ERROR: $PyWechatRoot exists but pyweixin source was not found." -ForegroundColor Red
        exit 1
    }
    Write-Host "Cloning WeChat UI automation helper..." -ForegroundColor Cyan
    git clone https://github.com/Hello-Mr-Crab/pywechat.git $PyWechatRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "Installing pyweixin/pywechat UI automation package..." -ForegroundColor Cyan
python -m pip install -e "$PyWechatRoot\src"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$template = ".\config\monitoring.wechat.windows.json"
if (-not (Test-Path $template)) {
    Write-Host "ERROR: template config missing: $template" -ForegroundColor Red
    exit 1
}
$cfg = Get-Content $template -Raw -Encoding UTF8 | ConvertFrom-Json
$cfg.data_root = $dataRoot
$cfg.pywechat_root = $PyWechatRoot
$json = $cfg | ConvertTo-Json -Depth 20
[System.IO.File]::WriteAllText(
    (Join-Path $RepoRoot $LocalConfig),
    $json,
    (New-Object System.Text.UTF8Encoding($false))
)

$chromeCandidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$chrome = $chromeCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($chrome) {
    Write-Host "Chrome: OK ($chrome)" -ForegroundColor Green
} else {
    Write-Host "WARNING: Chrome not found. wechat_mp requires Google Chrome." -ForegroundColor Yellow
}

$wechatProc = Get-Process -Name Weixin,WeChat -ErrorAction SilentlyContinue | Select-Object -First 1
if ($wechatProc) {
    Write-Host "WeChat process: detected" -ForegroundColor Green
} else {
    Write-Host "WARNING: WeChat desktop is not running. wechat_channels requires the official Windows WeChat client to be installed and logged in." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Setup completed." -ForegroundColor Green
Write-Host "Local config: $LocalConfig" -ForegroundColor Cyan
Write-Host "Before running:" -ForegroundColor Yellow
Write-Host "  1. Set DASHSCOPE_API_KEY in the current PowerShell session." -ForegroundColor Yellow
Write-Host "  2. For Channels, open official WeChat desktop and complete normal login first." -ForegroundColor Yellow
Write-Host "  3. If Sogou/WeChat shows official verification, complete it manually; scripts do not bypass verification." -ForegroundColor Yellow
