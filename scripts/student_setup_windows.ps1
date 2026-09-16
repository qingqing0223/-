param(
    [string]$MediaCrawlerRoot = "E:\MediaCrawler_clean"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

foreach ($cmd in @("git", "python", "uv", "node")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "ERROR: required command not found: $cmd" -ForegroundColor Red
        exit 1
    }
}

$pythonCmd = Get-Command python -ErrorAction Stop
$PythonExe = $pythonCmd.Source

$chromeCandidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$ChromePath = $chromeCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $ChromePath) {
    Write-Host "ERROR: Google Chrome was not found. Install Chrome before continuing." -ForegroundColor Red
    exit 1
}

Write-Host "=== Student machine setup ===" -ForegroundColor Cyan
Write-Host "Integration repo: $RepoRoot" -ForegroundColor Cyan
Write-Host "MediaCrawler:     $MediaCrawlerRoot" -ForegroundColor Cyan
Write-Host "Python:           $PythonExe" -ForegroundColor Cyan
Write-Host "Python version:   $(& $PythonExe --version)" -ForegroundColor Cyan
Write-Host "Node.js:          $(node --version)" -ForegroundColor Cyan
Write-Host "Chrome:           $ChromePath" -ForegroundColor Cyan

Write-Host "Installing integration classifier package..." -ForegroundColor Cyan
& $PythonExe -m pip install -r .\requirements.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $PythonExe -c "import opinion_monitor_v2; print('opinion_monitor_v2 import OK:', opinion_monitor_v2.__file__)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: opinion_monitor_v2 cannot be imported by $PythonExe after installation." -ForegroundColor Red
    exit $LASTEXITCODE
}

if (-not (Test-Path (Join-Path $MediaCrawlerRoot "main.py"))) {
    if (Test-Path $MediaCrawlerRoot) {
        Write-Host "ERROR: $MediaCrawlerRoot exists but main.py was not found." -ForegroundColor Red
        Write-Host "This usually means a previous MediaCrawler clone was interrupted. If this is a new student deployment and the folder contains no data you need, remove that incomplete folder and rerun this setup." -ForegroundColor Yellow
        exit 1
    }

    Write-Host "MediaCrawler not found; cloning upstream repository..." -ForegroundColor Yellow
    $cloneOk = $false
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        Write-Host "MediaCrawler clone attempt $attempt/3..." -ForegroundColor Cyan
        git clone --depth 1 https://github.com/NanmiCoder/MediaCrawler.git $MediaCrawlerRoot
        if ($LASTEXITCODE -eq 0 -and (Test-Path (Join-Path $MediaCrawlerRoot "main.py"))) {
            $cloneOk = $true
            break
        }
        if (Test-Path $MediaCrawlerRoot) {
            Remove-Item $MediaCrawlerRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
        if ($attempt -lt 3) { Start-Sleep -Seconds 5 }
    }
    if (-not $cloneOk) {
        Write-Host "ERROR: MediaCrawler clone failed after 3 attempts. Check the network and rerun this setup." -ForegroundColor Red
        exit 1
    }
}

Write-Host "Installing/synchronizing MediaCrawler dependencies..." -ForegroundColor Cyan
Push-Location $MediaCrawlerRoot
uv sync
$uvCode = $LASTEXITCODE
Pop-Location
if ($uvCode -ne 0) { exit $uvCode }

# Keep a visible persistent browser and align upstream defaults with the project's
# full monitoring matrix. Runtime CLI arguments still take precedence.
$baseConfig = Join-Path $MediaCrawlerRoot "config\base_config.py"
if (Test-Path $baseConfig) {
    $text = [System.IO.File]::ReadAllText($baseConfig, [System.Text.Encoding]::UTF8)
    $changes = @{
        'HEADLESS' = 'False'
        'SAVE_LOGIN_STATE' = 'True'
        'ENABLE_CDP_MODE' = 'True'
        'CDP_HEADLESS' = 'False'
        'CDP_CONNECT_EXISTING' = 'False'
        'AUTO_CLOSE_BROWSER' = 'False'
        'ENABLE_GET_COMMENTS' = 'True'
        'ENABLE_GET_SUB_COMMENTS' = 'True'
        'CRAWLER_MAX_NOTES_COUNT' = '100000'
        'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES' = '100000'
        'MAX_CONCURRENCY_NUM' = '1'
    }
    $changed = $false
    foreach ($name in $changes.Keys) {
        $pattern = "(?m)^\s*" + [regex]::Escape($name) + "\s*=\s*.*$"
        if ([regex]::IsMatch($text, $pattern)) {
            $replacement = "$name = $($changes[$name])"
            $newText = [regex]::Replace($text, $pattern, $replacement)
            if ($newText -ne $text) { $changed = $true }
            $text = $newText
        }
    }
    if ($changed) {
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($baseConfig, $text, $utf8NoBom)
        Write-Host "MediaCrawler full-matrix defaults prepared." -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "Base installation completed." -ForegroundColor Green
Write-Host "Before monitoring:" -ForegroundColor Cyan
Write-Host "  1. Set DASHSCOPE_API_KEY locally in PowerShell (do not commit it)." -ForegroundColor Yellow
Write-Host "  2. Authenticate Git with your own GitHub account if you need -PushGithub." -ForegroundColor Yellow
Write-Host "  3. Run: python .\scripts\preflight.py --config .\config\monitoring.local.json" -ForegroundColor Yellow
Write-Host "  4. Run one assigned platform with scripts\start_student_platform_windows.ps1." -ForegroundColor Yellow
Write-Host "Full matrix defaults: natural-end paging (100000 safety cap), first-level comments, nested comments and comment ingestion." -ForegroundColor Yellow
Write-Host "Platform login/verification must be completed manually through the platform's official UI when requested." -ForegroundColor Yellow
