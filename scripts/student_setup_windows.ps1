param(
    [string]$MediaCrawlerRoot = "E:\MediaCrawler_clean"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot
$PinnedMediaCrawlerCommit = "60e66f2a925816960bbd44af5d6c9b8385d79335"

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
Write-Host "Pinned MC commit: $PinnedMediaCrawlerCommit" -ForegroundColor Cyan
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
        git clone https://github.com/NanmiCoder/MediaCrawler.git $MediaCrawlerRoot
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

if (-not (Test-Path (Join-Path $MediaCrawlerRoot ".git"))) {
    Write-Host "ERROR: MediaCrawler root is not a Git checkout: $MediaCrawlerRoot" -ForegroundColor Red
    exit 1
}

Write-Host "Pinning MediaCrawler to the tested upstream commit..." -ForegroundColor Cyan
Push-Location $MediaCrawlerRoot
git fetch origin $PinnedMediaCrawlerCommit --depth 1 | Out-Host
$fetchCode = $LASTEXITCODE
if ($fetchCode -eq 0) {
    git checkout --force $PinnedMediaCrawlerCommit | Out-Host
    $checkoutCode = $LASTEXITCODE
} else {
    $checkoutCode = $fetchCode
}
Pop-Location
if ($checkoutCode -ne 0) {
    Write-Host "ERROR: failed to pin MediaCrawler to $PinnedMediaCrawlerCommit." -ForegroundColor Red
    exit $checkoutCode
}

Write-Host "Installing/synchronizing MediaCrawler dependencies..." -ForegroundColor Cyan
Push-Location $MediaCrawlerRoot
uv sync
$uvCode = $LASTEXITCODE
Pop-Location
if ($uvCode -ne 0) { exit $uvCode }

# The upstream teaching build intentionally strips public IP-location labels before
# JSONL persistence. Our monitoring only needs the coarse region label already shown
# publicly by the platform (e.g. 山东/北京), never a real IP address or precise location.
# Apply the project-maintained, idempotent patch centrally so every student machine
# uses the same pinned and tested source. Any mismatch fails setup immediately.
$regionPatch = Join-Path $RepoRoot "scripts\patch_mediacrawler_public_regions.py"
$regionVerify = Join-Path $RepoRoot "scripts\verify_mediacrawler_public_regions.py"
if (-not (Test-Path $regionPatch)) {
    Write-Host "ERROR: public-region patch script is missing: $regionPatch" -ForegroundColor Red
    exit 12
}
if (-not (Test-Path $regionVerify)) {
    Write-Host "ERROR: public-region verification script is missing: $regionVerify" -ForegroundColor Red
    exit 12
}
Write-Host "Applying public-region persistence patch..." -ForegroundColor Cyan
& $PythonExe $regionPatch --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: public-region patch failed. Do not start monitoring with a partially patched MediaCrawler." -ForegroundColor Red
    exit $LASTEXITCODE
}
$regionManifest = Join-Path $MediaCrawlerRoot ".promotion_week_public_region_patch.json"
if (-not (Test-Path $regionManifest)) {
    Write-Host "ERROR: public-region patch manifest was not created." -ForegroundColor Red
    exit 13
}
Write-Host "Verifying every public-region field path..." -ForegroundColor Cyan
& $PythonExe $regionPatch --root $MediaCrawlerRoot --check
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: public-region patch self-check failed. Monitoring will not start." -ForegroundColor Red
    exit $LASTEXITCODE
}
& $PythonExe $regionVerify --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: public-region semantic verification failed. Monitoring will not start." -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "Public-region patch fully verified: $regionManifest" -ForegroundColor Green

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
Write-Host "Public-region labels are retained only when exposed by the platform; real IP addresses and precise locations are not stored." -ForegroundColor Yellow
Write-Host "Platform login/verification must be completed manually through the platform's official UI when requested." -ForegroundColor Yellow
