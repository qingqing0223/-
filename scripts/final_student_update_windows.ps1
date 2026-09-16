param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","tieba","zhihu")]
    [string]$Platform,

    [Parameter(Mandatory=$true)]
    [string]$NodeId,

    [string]$Config = ".\config\monitoring.local.json",
    [switch]$Start
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

Write-Host "=== FINAL student monitoring upgrade ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "NodeId:   $NodeId" -ForegroundColor Cyan
Write-Host ""
Write-Host "IMPORTANT: close the old collector window and the old GitHub-sync window before running this script." -ForegroundColor Yellow

try {
    $running = Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.CommandLine -and (
            $_.CommandLine -match "run_single_platform.py" -or
            $_.CommandLine -match "publish_node_result_to_github.py"
        )
    }
    if ($running) {
        Write-Host "ERROR: old monitoring/sync processes are still running." -ForegroundColor Red
        $running | Select-Object ProcessId, Name, CommandLine | Format-Table -AutoSize
        Write-Host "Close those old monitoring PowerShell windows, then rerun this command." -ForegroundColor Yellow
        exit 2
    }
} catch {
    Write-Host "Warning: process check was unavailable; continuing." -ForegroundColor Yellow
}

if (-not $env:DASHSCOPE_API_KEY) {
    Write-Host "ERROR: DASHSCOPE_API_KEY is not set in this PowerShell session." -ForegroundColor Red
    Write-Host "Set it locally first, then rerun this script." -ForegroundColor Yellow
    exit 3
}

# Preserve any local Git state before aligning this working tree with origin/main.
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = "backup-final-student-$stamp"
$head = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -eq 0 -and $head) {
    git branch $backup $head 2>$null
}

$gitDir = (git rev-parse --git-dir).Trim()
if ($LASTEXITCODE -eq 0 -and $gitDir) {
    $rebaseMerge = Join-Path $gitDir "rebase-merge"
    $rebaseApply = Join-Path $gitDir "rebase-apply"
    if ((Test-Path $rebaseMerge) -or (Test-Path $rebaseApply)) {
        Write-Host "Aborting an unfinished Git rebase from an earlier run..." -ForegroundColor Yellow
        git rebase --abort
    }
}

git stash push -u -m "final-student-upgrade-$stamp" | Out-Host
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

git fetch origin | Out-Host
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

git switch -C main origin/main | Out-Host
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Repository aligned with origin/main. Backup branch: $backup" -ForegroundColor Green

if (-not (Test-Path $Config)) {
    Write-Host "ERROR: machine-local config not found: $Config" -ForegroundColor Red
    Write-Host "The local config is intentionally not stored in GitHub. Restore/create it before continuing." -ForegroundColor Yellow
    exit 4
}

$cfgObj = Get-Content $Config -Raw -Encoding UTF8 | ConvertFrom-Json
$MediaCrawlerRoot = [string]$cfgObj.media_crawler_root
if (-not $MediaCrawlerRoot) {
    $MediaCrawlerRoot = "E:\MediaCrawler_clean"
}

Write-Host "Refreshing integration package and MediaCrawler defaults..." -ForegroundColor Cyan
.\scripts\student_setup_windows.ps1 -MediaCrawlerRoot $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Running final preflight..." -ForegroundColor Cyan
python .\scripts\preflight.py --config $Config
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: final preflight failed. Send the JSON result to the coordinator; do not start another collector." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "FINAL upgrade completed." -ForegroundColor Green
Write-Host "Enabled collection/reporting scope:" -ForegroundColor Cyan
Write-Host "  - 6 official campaign keywords" -ForegroundColor Yellow
Write-Host "  - search pagination to natural end with a finite safety cap" -ForegroundColor Yellow
Write-Host "  - cross-cycle dedupe and 5-minute incremental polling" -ForegroundColor Yellow
Write-Host "  - public post/video detail and engagement fields" -ForegroundColor Yellow
Write-Host "  - first-level comments and nested replies" -ForegroundColor Yellow
Write-Host "  - parent/root reply reconstruction" -ForegroundColor Yellow
Write-Host "  - public IP-region labels when the platform exposes them" -ForegroundColor Yellow
Write-Host "  - v2 attitude classification for posts/videos/comments" -ForegroundColor Yellow
Write-Host "  - support / neutral / attention / non-support reporting buckets" -ForegroundColor Yellow
Write-Host "  - Chinese/minority-language detection" -ForegroundColor Yellow
Write-Host "  - public publisher account aggregate statistics" -ForegroundColor Yellow
Write-Host "  - video ASR/OCR completeness diagnostics when those fields exist" -ForegroundColor Yellow
Write-Host "  - GitHub aggregate result synchronization" -ForegroundColor Yellow
Write-Host "  - watchdog restart for ordinary failures; official login/verification remains manual" -ForegroundColor Yellow
Write-Host ""

if ($Start) {
    Write-Host "Starting final monitor now..." -ForegroundColor Green
    .\scripts\start_student_platform_windows.ps1 -Platform $Platform -NodeId $NodeId -Config $Config -PushGithub
} else {
    Write-Host "Start command:" -ForegroundColor Cyan
    Write-Host ".\scripts\start_student_platform_windows.ps1 -Platform $Platform -NodeId $NodeId -Config $Config -PushGithub" -ForegroundColor Green
}
