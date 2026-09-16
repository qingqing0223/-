param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","tieba","zhihu")]
    [string]$Platform,

    [Parameter(Mandatory=$true)]
    [string]$NodeId,

    [string]$Config = ".\config\monitoring.local.json"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

$rawRepo = [string]$env:PROMOTION_RAW_ARCHIVE_REPO
$autoRaw = ([string]$env:PROMOTION_RAW_ARCHIVE_AUTO).ToLower() -in @("1", "true", "yes", "y")
$privateConfirmed = ([string]$env:PROMOTION_RAW_ARCHIVE_PRIVATE_CONFIRMED).ToLower() -in @("1", "true", "yes", "y")

Write-Host "=== FINAL five-minute student monitoring launcher ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "NodeId:   $NodeId" -ForegroundColor Cyan
Write-Host "Public result sync: ON (300 seconds)" -ForegroundColor Green

$argsList = @(
    "-Platform", $Platform,
    "-NodeId", $NodeId,
    "-Config", $Config,
    "-PushGithub"
)

if ($autoRaw -and $rawRepo -and $privateConfirmed -and (Test-Path (Join-Path $rawRepo ".git"))) {
    $argsList += @(
        "-ArchiveRaw",
        "-RawArchiveRepo", $rawRepo,
        "-PrivateRepoConfirmed"
    )
    Write-Host "Private raw/GPT feed sync: ON (300 seconds)" -ForegroundColor Green
    Write-Host "Private archive: $rawRepo" -ForegroundColor Green
} else {
    Write-Host "Private raw/GPT feed sync: OFF" -ForegroundColor Yellow
    Write-Host "Run .\scripts\configure_private_raw_archive_windows.ps1 once if full raw + GPT-readable private data should return to GitHub automatically." -ForegroundColor Yellow
}

Write-Host "Attitude classifier availability does NOT control collection." -ForegroundColor Yellow
Write-Host "If the external classifier reports arrears/quota/API errors, collected posts/comments are retained and marked unclassified/degraded instead of being discarded." -ForegroundColor Yellow
Write-Host "Official login/captcha/security verification still requires normal manual completion." -ForegroundColor Yellow

& .\scripts\start_student_platform_windows.ps1 @argsList
exit $LASTEXITCODE
