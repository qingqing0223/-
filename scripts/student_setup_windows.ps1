param(
    [string]$MediaCrawlerRoot = "E:\MediaCrawler_clean"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

foreach ($cmd in @("git", "python", "uv")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "ERROR: required command not found: $cmd" -ForegroundColor Red
        exit 1
    }
}

Write-Host "=== Student machine setup ===" -ForegroundColor Cyan
Write-Host "Integration repo: $RepoRoot" -ForegroundColor Cyan
Write-Host "MediaCrawler:     $MediaCrawlerRoot" -ForegroundColor Cyan

if (-not (Test-Path (Join-Path $MediaCrawlerRoot "main.py"))) {
    if (Test-Path $MediaCrawlerRoot) {
        Write-Host "ERROR: $MediaCrawlerRoot exists but main.py was not found. Move/remove it or pass another -MediaCrawlerRoot." -ForegroundColor Red
        exit 1
    }
    Write-Host "MediaCrawler not found; cloning upstream repository..." -ForegroundColor Yellow
    git clone https://github.com/NanmiCoder/MediaCrawler.git $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "Installing/synchronizing MediaCrawler dependencies..." -ForegroundColor Cyan
Push-Location $MediaCrawlerRoot
uv sync
$uvCode = $LASTEXITCODE
Pop-Location
if ($uvCode -ne 0) { exit $uvCode }

Write-Host "Installing integration classifier package..." -ForegroundColor Cyan
Set-Location $RepoRoot
python -m pip install -r .\requirements.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "" 
Write-Host "Base installation completed." -ForegroundColor Green
Write-Host "Before monitoring:" -ForegroundColor Cyan
Write-Host "  1. Set DASHSCOPE_API_KEY locally in PowerShell (do not commit it)." -ForegroundColor Yellow
Write-Host "  2. Authenticate Git with your own GitHub account if you need -PushGithub." -ForegroundColor Yellow
Write-Host "  3. Run: python .\scripts\preflight.py" -ForegroundColor Yellow
Write-Host "  4. Run one assigned platform with scripts\start_student_platform_windows.ps1." -ForegroundColor Yellow
Write-Host "Platform login/verification must be completed manually through the platform's official UI when requested." -ForegroundColor Yellow
