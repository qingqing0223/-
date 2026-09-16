param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","tieba","zhihu")]
    [string]$Platform,

    [string]$NodeId = $env:COMPUTERNAME,
    [string]$Config = ".\config\monitoring.student.windows.json",
    [switch]$PushGithub,
    [switch]$NoWatchdog
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

if (-not $env:DASHSCOPE_API_KEY) {
    Write-Host "ERROR: DASHSCOPE_API_KEY is not set in this PowerShell session." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $Config)) {
    Write-Host "ERROR: config not found: $Config" -ForegroundColor Red
    exit 1
}
if (-not $NodeId) {
    $NodeId = "student-node"
}

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "ERROR: python was not found in this PowerShell session." -ForegroundColor Red
    exit 1
}
$PythonExe = $pythonCmd.Source
Write-Host "Python:   $PythonExe" -ForegroundColor Cyan

# PowerShell 5.1 may turn stderr from a native executable into a terminating
# NativeCommandError. Probe/install the local v2 package without letting that
# behavior stop the self-repair path.
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $PythonExe -c "import opinion_monitor_v2" 2>$null
$importCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference

if ($importCode -ne 0) {
    Write-Host "Local classifier package is missing; installing packages/v2..." -ForegroundColor Yellow
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $PythonExe -m pip install -e (Join-Path $RepoRoot "packages\v2")
    $installCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    if ($installCode -ne 0) {
        Write-Host "ERROR: failed to install packages/v2." -ForegroundColor Red
        exit $installCode
    }
}

# Upgrade old machine-local configs to the final monitoring matrix while keeping
# each student's own disk paths/dashboard settings.
$resolvedConfig = (Resolve-Path $Config).Path
if ([System.IO.Path]::GetFileName($resolvedConfig) -like "*.local.json") {
    $cfgObj = Get-Content $resolvedConfig -Raw -Encoding UTF8 | ConvertFrom-Json
    function Set-ConfigProperty($obj, [string]$name, $value) {
        if ($obj.PSObject.Properties.Name -contains $name) {
            $obj.$name = $value
        } else {
            $obj | Add-Member -NotePropertyName $name -NotePropertyValue $value
        }
    }
    Set-ConfigProperty $cfgObj "results_date" ""
    Set-ConfigProperty $cfgObj "results_date_mode" "auto"
    Set-ConfigProperty $cfgObj "interval_seconds" 300
    Set-ConfigProperty $cfgObj "overrun_cooldown_seconds" 60
    Set-ConfigProperty $cfgObj "soft_empty_cooldown_seconds" 3600
    Set-ConfigProperty $cfgObj "network_error_cooldown_seconds" 300
    Set-ConfigProperty $cfgObj "search_until_exhausted" $true
    Set-ConfigProperty $cfgObj "crawler_max_notes_count" 100000
    Set-ConfigProperty $cfgObj "comments_until_exhausted" $true
    Set-ConfigProperty $cfgObj "max_comments_count_singlenotes" 100000
    Set-ConfigProperty $cfgObj "get_comment" "yes"
    Set-ConfigProperty $cfgObj "get_sub_comment" "yes"
    Set-ConfigProperty $cfgObj "ingest_comments" $true
    Set-ConfigProperty $cfgObj "detail_comment_recovery" $true
    Set-ConfigProperty $cfgObj "detail_comment_recovery_max_items" 30
    Set-ConfigProperty $cfgObj "detail_comment_recovery_batch_size" 10
    Set-ConfigProperty $cfgObj "github_diagnostic_samples" $true
    Set-ConfigProperty $cfgObj "github_diagnostic_sample_rows_per_type" 5
    Set-ConfigProperty $cfgObj "max_concurrency_num" 1
    $json = $cfgObj | ConvertTo-Json -Depth 100
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($resolvedConfig, $json, $utf8NoBom)
    Write-Host "Local config upgraded to final five-minute full-matrix mode." -ForegroundColor Green
}

# Do not allow two main platform collectors to run on the same student machine.
try {
    $existing = Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.Name -match "python" -and $_.CommandLine -and
        $_.CommandLine -match "run_single_platform.py" -and
        $_.CommandLine -match "--platform\s+$Platform(\s|$)"
    }
    if ($existing) {
        Write-Host "ERROR: another $Platform collector is already running on this machine." -ForegroundColor Red
        Write-Host "Stop the old monitoring window first, then start the final version once." -ForegroundColor Yellow
        exit 2
    }
} catch {
    Write-Host "Warning: duplicate-process check unavailable; continuing." -ForegroundColor Yellow
}

Write-Host "Running final preflight..." -ForegroundColor Cyan
& $PythonExe .\scripts\preflight.py --config $Config
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: preflight failed. Do not start monitoring until required_failures is 0." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "=== FINAL student distributed platform monitor ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "NodeId:   $NodeId" -ForegroundColor Cyan
Write-Host "Config:   $Config" -ForegroundColor Cyan
Write-Host "Realtime target: new monitoring cycle starts every 300 seconds when the previous cycle completes within five minutes." -ForegroundColor Yellow
Write-Host "If a crawl itself exceeds five minutes, the system records an SLA miss and does NOT overlap a second collector; verification/login/soft-empty states also use safe cooldowns." -ForegroundColor Yellow
Write-Host "Enabled: 6-keyword search, natural-end paging, dedupe, details, first-level comments, nested comments, parent/reply links, public IP-region fields when exposed, language/minority-language detection, v2 attitude classification for posts/videos/comments, public publisher account statistics, engagement statistics, and GitHub aggregate sync." -ForegroundColor Yellow
Write-Host "GitHub sync also carries privacy-safe raw JSONL diagnostics (schema/row-count/hash/structural linkage samples) every five minutes; full raw text stays local because this repository is public." -ForegroundColor Yellow
Write-Host "GitHub result paths roll automatically by the current date; do not manually pin results_date to an old day." -ForegroundColor Yellow
Write-Host "Video ASR/OCR is reported when those fields are available; missing ASR/OCR is explicitly visible in summary diagnostics." -ForegroundColor Yellow
Write-Host "Official login/captcha/security verification must be completed manually when requested." -ForegroundColor Yellow

if ($PushGithub) {
    $syncCmd = "Set-Location '$RepoRoot'; .\scripts\start_node_results_sync_windows.ps1 -Platform $Platform -NodeId '$NodeId' -Config '$Config' -Push"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $syncCmd
    Write-Host "GitHub aggregate + diagnostic shard sync started in a separate window." -ForegroundColor Green
} else {
    Write-Host "GitHub push is OFF. Add -PushGithub after this machine has Git write access." -ForegroundColor Yellow
}

if ($NoWatchdog) {
    & $PythonExe .\run_single_platform.py --platform $Platform --config $Config
} else {
    .\scripts\watch_single_platform_windows.ps1 -Platform $Platform -Config $Config
}
