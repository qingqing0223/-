param(
    [Parameter(Mandatory=$true)]
    [string]$RepoUrl,

    [string]$ArchiveRepo = "E:\promotion-week-raw-private",
    [switch]$PrivateRepoConfirmed
)

$ErrorActionPreference = "Stop"

if (-not $PrivateRepoConfirmed) {
    Write-Host "ERROR: this setup is only for an access-controlled PRIVATE Git repository." -ForegroundColor Red
    Write-Host "Confirm the repository is private, then rerun with -PrivateRepoConfirmed." -ForegroundColor Yellow
    exit 2
}

# Private GitHub repositories deliberately return "Repository not found" when the
# current HTTPS Git credential is missing or does not have access. Check access
# before cloning so the error is diagnosed as authentication rather than as a
# missing repository.
Write-Host "Checking private GitHub repository access with current Windows Git credentials..." -ForegroundColor Cyan
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
git ls-remote $RepoUrl HEAD | Out-Host
$remoteAccessCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($remoteAccessCode -ne 0) {
    Write-Host "" 
    Write-Host "ERROR: Git cannot access the private repository with the credential currently cached for github.com." -ForegroundColor Red
    Write-Host "The repository may exist and be visible in the browser; GitHub returns 'Repository not found' to unauthenticated/unauthorized Git clients for private repositories." -ForegroundColor Yellow
    Write-Host "Fix the Windows Git credential, then rerun this setup." -ForegroundColor Yellow
    Write-Host "Recommended PowerShell steps:" -ForegroundColor Cyan
    Write-Host '  @"' -ForegroundColor Gray
    Write-Host '  protocol=https' -ForegroundColor Gray
    Write-Host '  host=github.com' -ForegroundColor Gray
    Write-Host '  ' -ForegroundColor Gray
    Write-Host '  "@ | git credential reject' -ForegroundColor Gray
    Write-Host '  git credential-manager github login' -ForegroundColor Gray
    Write-Host "Then complete the normal GitHub browser sign-in for the account that owns/has access to the private repository." -ForegroundColor Yellow
    exit 4
}

$parent = Split-Path -Parent $ArchiveRepo
if ($parent -and -not (Test-Path $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}

if (Test-Path (Join-Path $ArchiveRepo ".git")) {
    Write-Host "Private archive clone already exists: $ArchiveRepo" -ForegroundColor Cyan
    git -C $ArchiveRepo remote set-url origin $RepoUrl
    git -C $ArchiveRepo fetch origin
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    git -C $ArchiveRepo pull --rebase
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} elseif (Test-Path $ArchiveRepo) {
    Write-Host "ERROR: path exists but is not a Git clone: $ArchiveRepo" -ForegroundColor Red
    exit 3
} else {
    Write-Host "Cloning private raw-data repository..." -ForegroundColor Cyan
    git clone $RepoUrl $ArchiveRepo
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# Make first push robust even when the user created an empty private repository.
# GitHub normally uses main as the default branch, but an empty clone can leave the
# local HEAD unborn or without an upstream. The archive process should not require
# the user to manually create a README first.
git -C $ArchiveRepo config push.autoSetupRemote true
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
git -C $ArchiveRepo rev-parse --verify HEAD *> $null
$hasCommit = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $previousErrorActionPreference
if (-not $hasCommit) {
    git -C $ArchiveRepo symbolic-ref HEAD refs/heads/main
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "Empty private repository detected; local first-push branch prepared as main." -ForegroundColor Cyan
}

Write-Host "Checking GitHub authentication/write target..." -ForegroundColor Cyan
git -C $ArchiveRepo ls-remote origin HEAD | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: cannot access the archive repository with the current Git credentials." -ForegroundColor Red
    exit $LASTEXITCODE
}

# Persist for future PowerShell sessions and also set the current session.
[Environment]::SetEnvironmentVariable("PROMOTION_RAW_ARCHIVE_REPO", $ArchiveRepo, "User")
[Environment]::SetEnvironmentVariable("PROMOTION_RAW_ARCHIVE_AUTO", "1", "User")
[Environment]::SetEnvironmentVariable("PROMOTION_RAW_ARCHIVE_PRIVATE_CONFIRMED", "1", "User")
$env:PROMOTION_RAW_ARCHIVE_REPO = $ArchiveRepo
$env:PROMOTION_RAW_ARCHIVE_AUTO = "1"
$env:PROMOTION_RAW_ARCHIVE_PRIVATE_CONFIRMED = "1"

Write-Host ""
Write-Host "Private raw archive configured." -ForegroundColor Green
Write-Host "Archive path: $ArchiveRepo" -ForegroundColor Green
Write-Host "Future final-start wrapper runs will automatically enable 300-second raw archive sync." -ForegroundColor Green
Write-Host "The private repo will receive:" -ForegroundColor Cyan
Write-Host "  - full raw JSONL as .jsonl.gz with SHA-256 + row-count manifest" -ForegroundColor Yellow
Write-Host "  - latest_status.json" -ForegroundColor Yellow
Write-Host "  - latest_gpt_feed.json (UTF-8, GPT-readable, refreshed every 300 seconds)" -ForegroundColor Yellow
Write-Host "Cookies, browser profiles, login state, API keys, raw network IPs and precise locations are excluded." -ForegroundColor Yellow
