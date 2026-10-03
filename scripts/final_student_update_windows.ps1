param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","toutiao","zhihu")]
    [string]$Platform,

    [Parameter(Mandatory=$true)]
    [string]$NodeId,

    [string]$Config = ".\config\monitoring.local.json",
    [switch]$Start,
    [switch]$ArchiveRaw,
    [string]$RawArchiveRepo = $env:PROMOTION_RAW_ARCHIVE_REPO,
    [switch]$PrivateRepoConfirmed,
    [switch]$ReviewSync,
    [string]$ReviewRepo = $env:PROMOTION_REVIEW_REPO,
    [switch]$PrivateReviewRepoConfirmed
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

Write-Host "=== FINAL student monitoring upgrade (five-minute realtime + region-aware build) ===" -ForegroundColor Cyan
Write-Host "Platform: $Platform" -ForegroundColor Cyan
Write-Host "NodeId:   $NodeId" -ForegroundColor Cyan
Write-Host ""

& .\scripts\final_student_update_base_windows.ps1 `
    -Platform $Platform `
    -NodeId $NodeId `
    -Config $Config
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: base final update failed; monitor was not started." -ForegroundColor Red
    exit $LASTEXITCODE
}

if (-not (Test-Path $Config)) {
    Write-Host "ERROR: machine-local config not found after base update: $Config" -ForegroundColor Red
    exit 20
}

$cfgObj = Get-Content $Config -Raw -Encoding UTF8 | ConvertFrom-Json
$MediaCrawlerRoot = [string]$cfgObj.media_crawler_root
if (-not $MediaCrawlerRoot) {
    $MediaCrawlerRoot = "E:\MediaCrawler_clean"
}

Write-Host ""
Write-Host "Applying coarse public IP-region persistence patch..." -ForegroundColor Cyan
python .\scripts\patch_mediacrawler_public_regions.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: MediaCrawler public-region patch failed. Monitor will NOT start." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "Verifying public-region patch..." -ForegroundColor Cyan
python .\scripts\verify_mediacrawler_public_regions.py --root $MediaCrawlerRoot
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: public-region verification failed. Monitor will NOT start." -ForegroundColor Red
    exit $LASTEXITCODE
}

if ($Platform -eq "dy") {
    Write-Host "Applying Douyin startup navigation resilience patch..." -ForegroundColor Cyan
    python .\scripts\patch_douyin_startup_resilience.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Douyin startup resilience patch failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    python .\scripts\patch_douyin_startup_resilience.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Douyin startup resilience verification failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }


    Write-Host "Applying Douyin public comment request-profile patch..." -ForegroundColor Cyan
    python .\scripts\patch_douyin_comment_request_profile.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Douyin comment request-profile patch failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    python .\scripts\patch_douyin_comment_request_profile.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Douyin comment request-profile verification failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

if ($Platform -eq "xhs") {
    Write-Host "Applying XHS bounded realtime / verification-stop patch..." -ForegroundColor Cyan
    python .\scripts\patch_xhs_realtime_resilience.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: XHS realtime resilience patch failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    python .\scripts\patch_xhs_realtime_resilience.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: XHS realtime resilience verification failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host "Applying XHS manual official-verification wait patch..." -ForegroundColor Cyan
    python .\scripts\patch_xhs_manual_verify_wait.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: XHS manual verification wait patch failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    python .\scripts\patch_xhs_manual_verify_wait.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: XHS manual verification wait verification failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host "Applying XHS first-level/nested comment hierarchy patch..." -ForegroundColor Cyan
    python .\scripts\patch_xhs_comment_hierarchy.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: XHS comment hierarchy patch failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    python .\scripts\patch_xhs_comment_hierarchy.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: XHS comment hierarchy verification failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host "Applying XHS strict public-region persistence patch..." -ForegroundColor Cyan
    python .\scripts\patch_xhs_public_regions.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: XHS public-region patch failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    python .\scripts\patch_xhs_public_regions.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: XHS public-region verification failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

if ($Platform -eq "wb") {
    Write-Host "Applying Weibo bounded realtime / anti-abuse stop patch..." -ForegroundColor Cyan
    python .\scripts\patch_weibo_realtime_resilience.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Weibo realtime resilience patch failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    python .\scripts\patch_weibo_realtime_resilience.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Weibo realtime resilience verification failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host "Applying Weibo first-level/nested comment hierarchy patch..." -ForegroundColor Cyan
    python .\scripts\patch_weibo_comment_hierarchy.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Weibo comment hierarchy patch failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    python .\scripts\patch_weibo_comment_hierarchy.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Weibo comment hierarchy verification failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host "Applying Weibo strict public-region persistence patch..." -ForegroundColor Cyan
    python .\scripts\patch_weibo_public_regions.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Weibo public-region patch failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    python .\scripts\patch_weibo_public_regions.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Weibo public-region verification failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host "Applying Weibo public identity / originality / Table5 profile patch..." -ForegroundColor Cyan
    python .\scripts\patch_weibo_public_identity.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Weibo public identity patch failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }

    python .\scripts\patch_weibo_public_identity.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Weibo public identity verification failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

if ($Platform -eq "bili") {
    Write-Host "Applying Bilibili session/login resilience patch..." -ForegroundColor Cyan
    python .\scripts\patch_bilibili_login_resilience.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Bilibili session/login resilience patch failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    python .\scripts\patch_bilibili_login_resilience.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Bilibili session/login resilience verification failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host "Applying Bilibili AV/AID detail comment recovery patch..." -ForegroundColor Cyan
    python .\scripts\patch_bilibili_comment_detail.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Bilibili AV/AID detail comment recovery patch failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    python .\scripts\patch_bilibili_comment_detail.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Bilibili AV/AID detail comment recovery verification failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host "Applying Bilibili HTTP transport resilience patch..." -ForegroundColor Cyan
    python .\scripts\patch_bilibili_network_resilience.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Bilibili HTTP transport resilience patch failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    python .\scripts\patch_bilibili_network_resilience.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Bilibili HTTP transport resilience verification failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host "Applying Bilibili realtime nested-comment bounds patch..." -ForegroundColor Cyan
    python .\scripts\patch_bilibili_realtime_comment_bounds.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Bilibili realtime nested-comment bounds patch failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    python .\scripts\patch_bilibili_realtime_comment_bounds.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Bilibili realtime nested-comment bounds verification failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host "Applying Bilibili realtime newest-comment ordering patch..." -ForegroundColor Cyan
    python .\scripts\patch_bilibili_realtime_comment_order.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Bilibili realtime newest-comment ordering patch failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    python .\scripts\patch_bilibili_realtime_comment_order.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Bilibili realtime newest-comment ordering verification failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host "Applying Bilibili realtime discovery fan-out patch..." -ForegroundColor Cyan
    python .\scripts\patch_bilibili_realtime_discovery_bound.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Bilibili realtime discovery fan-out patch failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    python .\scripts\patch_bilibili_realtime_discovery_bound.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Bilibili realtime discovery fan-out verification failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

if ($Platform -eq "toutiao") {
    Write-Host "Verifying native Toutiao Playwright adapter..." -ForegroundColor Cyan
    python -m py_compile .\scripts\toutiao_crawler.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Toutiao adapter syntax verification failed. Monitor will NOT start." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    uv run --project $MediaCrawlerRoot python -c "import playwright; print('Toutiao Playwright runtime OK')"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Toutiao requires Playwright from the pinned MediaCrawler environment." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

if ($Platform -eq "ks") {
    Write-Host "Configuring Kuaishou browser lifecycle (self-launched CDP; no external 9222 dependency)..." -ForegroundColor Cyan
    & .\scripts\enable_mediacrawler_cdp.ps1 -MediaCrawlerRoot $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "Applying Kuaishou startup resilience patch..." -ForegroundColor Cyan
    python .\scripts\patch_kuaishou_startup_resilience.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python .\scripts\patch_kuaishou_startup_resilience.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "Applying Kuaishou session/login resilience patch..." -ForegroundColor Cyan
    python .\scripts\patch_kuaishou_login_resilience.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python .\scripts\patch_kuaishou_login_resilience.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "Applying Kuaishou public comment-region recovery patch..." -ForegroundColor Cyan
    python .\scripts\patch_kuaishou_comment_regions.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python .\scripts\patch_kuaishou_comment_regions.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "Applying Kuaishou comment-count + nested parent/root patch..." -ForegroundColor Cyan
    python .\scripts\patch_kuaishou_comment_hierarchy.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python .\scripts\patch_kuaishou_comment_hierarchy.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "Applying Kuaishou video/comment engagement persistence patch..." -ForegroundColor Cyan
    python .\scripts\patch_kuaishou_engagement_fields.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python .\scripts\patch_kuaishou_engagement_fields.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "Applying Kuaishou public follower/following/comment-like metrics patch..." -ForegroundColor Cyan
    python .\scripts\patch_kuaishou_creator_trial_safety.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python .\scripts\patch_kuaishou_creator_trial_safety.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    python .\scripts\patch_kuaishou_public_metrics.py --root $MediaCrawlerRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python .\scripts\patch_kuaishou_public_metrics.py --root $MediaCrawlerRoot --check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $env:KUAISHOU_PUBLIC_METRICS = "1"
}


Write-Host ""
Write-Host "FINAL build completed and verified." -ForegroundColor Green
Write-Host "Collection policy:" -ForegroundColor Cyan
Write-Host "  - one-time historical backfill is separate from the five-minute realtime loop" -ForegroundColor Yellow
Write-Host "  - realtime loop prioritizes new-content discovery every 300 seconds and queues deep comment crawling" -ForegroundColor Yellow
Write-Host "  - first-level + nested comments and parent/root links are retained when exposed" -ForegroundColor Yellow
Write-Host "  - Kuaishou persists video comment_count so comment-bearing videos enter the realtime detail queue" -ForegroundColor Yellow
Write-Host "  - only platform-displayed coarse IP-location labels are retained; real IP/precise location are rejected" -ForegroundColor Yellow
Write-Host "  - the public code repo receives aggregates + privacy-safe diagnostics only" -ForegroundColor Yellow
Write-Host "  - full raw JSONL can be synchronized separately to an access-controlled PRIVATE Git repository" -ForegroundColor Yellow
Write-Host ""
Write-Host "Before realtime monitoring, run one historical catch-up if this node has not done so:" -ForegroundColor Cyan
Write-Host ".\scripts\run_initial_backfill_windows.ps1 -Platform $Platform -Config $Config" -ForegroundColor Green
Write-Host ""

if ($Start) {
    Write-Host "Starting final five-minute realtime monitor now..." -ForegroundColor Green

    # Use hashtable splatting for named PowerShell parameters.
    # Array splatting would bind the literal string "-Platform" positionally
    # as the Platform value and fail ValidateSet.
    $startArgs = @{
        Platform   = $Platform
        NodeId     = $NodeId
        Config     = $Config
        PushGithub = $true
    }
    if ($ArchiveRaw) {
        $startArgs["ArchiveRaw"] = $true
        $startArgs["RawArchiveRepo"] = $RawArchiveRepo
        if ($PrivateRepoConfirmed) {
            $startArgs["PrivateRepoConfirmed"] = $true
        }
    }
    if ($ReviewSync) {
        $startArgs["ReviewSync"] = $true
        $startArgs["ReviewRepo"] = $ReviewRepo
        if ($PrivateReviewRepoConfirmed) {
            $startArgs["PrivateReviewRepoConfirmed"] = $true
        }
    }

    & .\scripts\start_student_platform_windows.ps1 @startArgs
    exit $LASTEXITCODE
}

Write-Host "Realtime start command:" -ForegroundColor Cyan
Write-Host ".\scripts\start_student_platform_windows.ps1 -Platform $Platform -NodeId $NodeId -Config $Config -PushGithub" -ForegroundColor Green

Write-Host ""
Write-Host "After at least one fresh collection cycle, verify public-region persistence with:" -ForegroundColor Cyan
Write-Host ".\scripts\check_public_region_acceptance_windows.ps1 -Platform $Platform -Config $Config" -ForegroundColor Green
if ($ReviewSync) {
    Write-Host "Realtime + private non-support review start command:" -ForegroundColor Cyan
    Write-Host ".\scripts\start_student_platform_windows.ps1 -Platform $Platform -NodeId $NodeId -Config $Config -PushGithub -ReviewSync -ReviewRepo '$ReviewRepo' -PrivateReviewRepoConfirmed" -ForegroundColor Green
}

if ($ArchiveRaw) {
    Write-Host "Realtime + private raw archive start command:" -ForegroundColor Cyan
    Write-Host ".\scripts\start_student_platform_windows.ps1 -Platform $Platform -NodeId $NodeId -Config $Config -PushGithub -ArchiveRaw -RawArchiveRepo '$RawArchiveRepo' -PrivateRepoConfirmed" -ForegroundColor Green
}
