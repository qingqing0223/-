param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","toutiao","zhihu")]
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
Write-Host "IMPORTANT: close any OLD collector/sync windows for THIS SAME PLATFORM before running this script." -ForegroundColor Yellow
Write-Host "Other platforms may keep running in parallel from their own working copies." -ForegroundColor Yellow

try {
    $escapedPlatform = [regex]::Escape($Platform)
    $platformArgPattern = "--platform\s+" + $escapedPlatform + "(?:\s|$)"
    $running = Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $cmd = [string]$_.CommandLine
        $scriptPlatformPattern = "(?:--platform|-Platform)\\s+" + $escapedPlatform + "(?:\\s|$)"
        $cmd -and (
            (($cmd -match "run_single_platform\\.py") -and ($cmd -match $platformArgPattern)) -or
            (($cmd -match "run_student_platform_final\\.py") -and ($cmd -match $platformArgPattern)) -or
            (($cmd -match "publish_node_result_to_github\\.py") -and ($cmd -match $platformArgPattern)) -or
            (($cmd -match "watch_student_platform_final_windows\\.ps1") -and ($cmd -match $scriptPlatformPattern)) -or
            (($cmd -match "start_node_results_sync_windows\\.ps1") -and ($cmd -match $scriptPlatformPattern))
        )
    }
    if ($running) {
        Write-Host "ERROR: an old collector/sync process for platform '$Platform' is still running on this computer." -ForegroundColor Red
        $running | Select-Object ProcessId, Name, CommandLine | Format-List
        Write-Host "Close only those SAME-PLATFORM old windows/processes, then rerun this command." -ForegroundColor Yellow
        exit 2
    }
} catch {
    Write-Host "Warning: process check was unavailable; continuing." -ForegroundColor Yellow
}

if (-not $env:DASHSCOPE_API_KEY) {
    Write-Host "DASHSCOPE_API_KEY is not set. Collection/update will continue; attitude classification will remain unclassified/degraded until an analysis node provides the model service." -ForegroundColor Yellow
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = "backup-final-student-$stamp"

# Preserve the machine-local config across "git stash -u".
# monitoring.local.json is intentionally not stored in GitHub, but -u also
# stashes untracked files. Without this temporary copy, the upgrade script
# would remove the config and then immediately fail its own existence check.
$localConfigBackup = $null
if (Test-Path $Config) {
    try {
        $localConfigBackup = Join-Path $env:TEMP ("promotion-monitoring-local-" + $stamp + ".json")
        Copy-Item -LiteralPath $Config -Destination $localConfigBackup -Force
        Write-Host "Preserved machine-local config before repository refresh." -ForegroundColor DarkGray
    } catch {
        Write-Host "ERROR: could not preserve machine-local config before repository refresh: $($_.Exception.Message)" -ForegroundColor Red
        exit 21
    }
}

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

# Restore only the local config we intentionally preserved. Do not pop the
# whole stash, because it may contain unrelated local work.
if ($localConfigBackup -and (Test-Path $localConfigBackup)) {
    try {
        $configParent = Split-Path -Parent $Config
        if ($configParent -and -not (Test-Path $configParent)) {
            New-Item -ItemType Directory -Path $configParent -Force | Out-Null
        }
        Copy-Item -LiteralPath $localConfigBackup -Destination $Config -Force
        Remove-Item -LiteralPath $localConfigBackup -Force -ErrorAction SilentlyContinue
        Write-Host "Restored machine-local config after repository refresh." -ForegroundColor DarkGray
    } catch {
        Write-Host "ERROR: could not restore machine-local config after repository refresh: $($_.Exception.Message)" -ForegroundColor Red
        exit 22
    }
}

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

Write-Host "Running monitoring regression tests..." -ForegroundColor Cyan
python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: regression tests failed. Monitor will NOT start on this build." -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "Regression tests passed." -ForegroundColor Green

Write-Host ""
Write-Host "FINAL upgrade completed." -ForegroundColor Green
Write-Host "Enabled collection/reporting scope:" -ForegroundColor Cyan
Write-Host "  - 6 official campaign keywords" -ForegroundColor Yellow
Write-Host "  - search pagination to natural end with a finite safety cap" -ForegroundColor Yellow
Write-Host "  - cross-cycle dedupe and incremental polling with risk-control cooldown" -ForegroundColor Yellow
Write-Host "  - public post/video detail and engagement fields" -ForegroundColor Yellow
Write-Host "  - first-level comments and nested replies" -ForegroundColor Yellow
Write-Host "  - parent/root reply reconstruction and integrity verification" -ForegroundColor Yellow
Write-Host "  - public IP-region labels when the platform exposes them" -ForegroundColor Yellow
Write-Host "  - optional v2 attitude classification when DASHSCOPE_API_KEY is configured; collection does not depend on it" -ForegroundColor Yellow
Write-Host "  - attitude/reporting buckets are analysis-stage outputs and may remain unclassified on collection-only nodes" -ForegroundColor Yellow
Write-Host "  - Chinese/minority-language detection" -ForegroundColor Yellow
Write-Host "  - public publisher account aggregate statistics" -ForegroundColor Yellow
Write-Host "  - video ASR/OCR completeness diagnostics when those fields exist" -ForegroundColor Yellow
Write-Host "  - GitHub aggregate result synchronization" -ForegroundColor Yellow
Write-Host "  - watchdog stop for official login/verification and cooldown for soft-empty/network states" -ForegroundColor Yellow
Write-Host ""

if ($Start) {
    Write-Host "Starting final monitor now..." -ForegroundColor Green
    .\scripts\start_student_platform_windows.ps1 -Platform $Platform -NodeId $NodeId -Config $Config -PushGithub
} else {
    Write-Host "Start command:" -ForegroundColor Cyan
    Write-Host ".\scripts\start_student_platform_windows.ps1 -Platform $Platform -NodeId $NodeId -Config $Config -PushGithub" -ForegroundColor Green
}
