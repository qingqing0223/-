param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","toutiao","zhihu","wechat_mp","wechat_channels")]
    [string]$Platform,

    [string]$NodeId = $env:COMPUTERNAME,
    [int]$IntervalSeconds = 300,
    [switch]$Push,
    [string]$Config = ".\config\monitoring.student.windows.json"
)

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

if ($IntervalSeconds -ne 300) {
    Write-Host "ERROR: IntervalSeconds must be exactly 300 seconds for this monitoring task." -ForegroundColor Red
    exit 1
}
if (-not $NodeId) {
    $NodeId = "student-node"
}
if (-not (Test-Path $Config)) {
    Write-Host "ERROR: config not found: $Config" -ForegroundColor Red
    exit 1
}

Write-Host "Starting distributed GitHub result sync" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "NodeId:   $NodeId" -ForegroundColor Cyan
Write-Host "Interval: $IntervalSeconds seconds (fixed five-minute sync)" -ForegroundColor Cyan
Write-Host "GitHub receives aggregate monitoring JSON plus privacy-safe raw diagnostics: raw JSONL filenames, row counts, file hashes, field/schema samples, stable hashes for content/comment/reply links, public coarse IP-region fields, and nested field names." -ForegroundColor Yellow
Write-Host "Raw post/comment text, raw user identifiers, raw URLs, real IP addresses, and precise locations are NOT published to this public repository." -ForegroundColor Yellow
Write-Host "Full original JSONL remains on the student machine for local retention; use a separate PRIVATE data repository if full raw archival is later required." -ForegroundColor Yellow

$argsList = @(
    ".\scripts\publish_node_result_to_github.py",
    "--platform", $Platform,
    "--node-id", $NodeId,
    "--config", $Config,
    "--loop",
    "--interval", $IntervalSeconds
)
if ($Push) {
    $argsList += "--push"
    Write-Host "Git push enabled. This computer must authenticate with its own GitHub account that has write access." -ForegroundColor Yellow

    # One-time GitHub push authentication preflight.
    # Let Git Credential Manager open the browser once here. After it succeeds,
    # the long-running 300-second sync loop is made non-interactive so it cannot
    # reopen a browser every cycle if the credential cache/helper is unhealthy.
    $branch = (git rev-parse --abbrev-ref HEAD).Trim()
    if (-not $branch -or $branch -eq "HEAD") {
        Write-Host "ERROR: repository is not on a normal branch; cannot preflight GitHub push authentication." -ForegroundColor Red
        exit 12
    }
    Write-Host "Synchronizing local branch with origin before GitHub push preflight..." -ForegroundColor Cyan

    # A previous interrupted Git operation can leave the index with unmerged
    # entries. Git pull then refuses to run. Do not let a harmless
    # "no rebase in progress" stderr become a terminating PowerShell error.
    $unmerged = @(& git diff --name-only --diff-filter=U 2>$null)
    if ($unmerged.Count -gt 0) {
        $nonResultConflicts = @($unmerged | Where-Object { $_ -notmatch '^(results/|results\\)' })
        if ($nonResultConflicts.Count -gt 0) {
            Write-Host "ERROR: unresolved Git conflicts exist outside generated results/. Manual review is required:" -ForegroundColor Red
            $nonResultConflicts | ForEach-Object { Write-Host ("  " + $_) -ForegroundColor Red }
            exit 15
        }

        Write-Host "Recovering interrupted generated-results Git state before sync..." -ForegroundColor Yellow
        & cmd.exe /d /c "git merge --abort >nul 2>&1"
        & cmd.exe /d /c "git rebase --abort >nul 2>&1"
        & cmd.exe /d /c "git cherry-pick --abort >nul 2>&1"
        & cmd.exe /d /c "git revert --abort >nul 2>&1"

        $stillUnmerged = @(& git diff --name-only --diff-filter=U 2>$null)
        if ($stillUnmerged.Count -gt 0) {
            # These paths are generated result shards only; reset them to HEAD.
            # The publisher regenerates the local node shard immediately.
            foreach ($conflictPath in $stillUnmerged) {
                & git restore --source=HEAD --staged --worktree -- $conflictPath 2>$null
            }
        }
    }

    git pull --rebase --autostash origin $branch | Out-Host
    if ($LASTEXITCODE -ne 0) {
        & cmd.exe /d /c "git rebase --abort >nul 2>&1"
        & cmd.exe /d /c "git merge --abort >nul 2>&1"
        Write-Host "ERROR: GitHub sync preflight could not update the local branch from origin." -ForegroundColor Red
        Write-Host "Resolve the Git pull/rebase issue, then restart this sync. This is not automatically treated as an authentication failure." -ForegroundColor Yellow
        exit 14
    }

    Write-Host "Checking GitHub push access once before the sync loop..." -ForegroundColor Cyan
    # Git writes normal push status (for example "To https://...") to stderr.
    # Under Windows PowerShell + ErrorActionPreference=Stop, capturing native
    # stderr with 2>&1 can be promoted to NativeCommandError even when Git exits 0.
    # Route the combined stream through cmd.exe so we can inspect the real exit code.
    $pushOutput = & cmd.exe /d /c ("git push --dry-run origin HEAD:" + $branch + " 2>&1")
    $pushExitCode = $LASTEXITCODE
    $pushOutput | Out-Host
    if ($pushExitCode -ne 0) {
        $pushText = ($pushOutput | Out-String).ToLowerInvariant()
        if ($pushText -match "authentication failed|could not read username|permission denied|repository not found|403|401|credential") {
            Write-Host "ERROR: GitHub push authentication/access preflight failed. Complete the browser sign-in once, then restart this sync." -ForegroundColor Red
        } else {
            Write-Host "WARNING: GitHub push dry-run saw a concurrent remote update." -ForegroundColor Yellow
            Write-Host "Continuing into the sync loop; the publisher has its own pull/rebase/retry logic for multi-node pushes." -ForegroundColor Yellow
            $pushExitCode = 0
        }
        if ($pushExitCode -ne 0) {
            exit 13
        }
    }
    if ($pushExitCode -eq 0) {
        Write-Host "GitHub push access preflight completed; sync loop will handle concurrent remote updates." -ForegroundColor Green
    }

    # Authentication is interactive only during this one-time preflight.
    # After a successful preflight, force the long-running five-minute sync loop
    # to be non-interactive. Otherwise Git Credential Manager can reopen the
    # browser on every pull/push retry, producing repeated "Connect to GitHub"
    # dialogs even though collection itself is healthy.
    #
    # If the cached GitHub credential later expires, the publisher will report a
    # git_*_auth failure in the terminal instead of repeatedly opening browser
    # windows. The operator can then restart this sync once and sign in once.
    $env:GCM_INTERACTIVE = "Never"
    $env:GIT_TERMINAL_PROMPT = "0"
} else {
    Write-Host "Git push disabled; summaries/diagnostics will only be generated locally." -ForegroundColor Yellow
}

python @argsList
