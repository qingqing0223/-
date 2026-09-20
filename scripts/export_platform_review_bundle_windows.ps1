param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("xhs","dy","ks","bili","wb","tieba","zhihu","wechat_mp")]
    [string]$Platform,

    [string]$Config = ".\config\monitoring.local.json",
    [string]$OutputRoot = "",
    [string]$Date = (Get-Date -Format "yyyy-MM-dd"),
    [switch]$Cumulative,
    [switch]$NoRawCopy
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

if (-not (Test-Path $Config)) {
    Write-Host "ERROR: config not found: $Config" -ForegroundColor Red
    exit 1
}

$cfg = Get-Content $Config -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $cfg.data_root) {
    Write-Host "ERROR: data_root is missing in config: $Config" -ForegroundColor Red
    exit 2
}

$base = [System.IO.Path]::GetFullPath([string]$cfg.data_root)
$leaf = Split-Path $base -Leaf
if ($leaf -like "*_$Platform") {
    $DataRoot = $base
} else {
    $DataRoot = Join-Path (Split-Path $base -Parent) ($leaf + "_" + $Platform)
}

if (-not $OutputRoot) {
    $OutputRoot = [Environment]::GetFolderPath("Desktop")
}
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)

$platformNames = @{
    xhs = "小红书"
    dy = "抖音"
    ks = "快手"
    bili = "B站"
    wb = "微博"
    tieba = "百度贴吧"
    zhihu = "知乎"
    wechat_mp = "微信公众号"
}
$PlatformName = [string]$platformNames[$Platform]

try {
    $TargetDate = [datetime]::ParseExact($Date, "yyyy-MM-dd", $null)
} catch {
    Write-Host "ERROR: -Date must use yyyy-MM-dd, for example 2026-09-20." -ForegroundColor Red
    exit 4
}
$TargetDateText = $TargetDate.ToString("yyyy-MM-dd")
$TargetDateCompact = $TargetDate.ToString("yyyyMMdd")
$ScopeLabel = if ($Cumulative) { "累计" } else { $TargetDateText }

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Out = Join-Path $OutputRoot ("{0}_{1}_{2}_原始数据与人工复核" -f $stamp, $PlatformName, $ScopeLabel)
$Zip = $Out + ".zip"

Remove-Item $Out -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $Zip -Force -ErrorAction SilentlyContinue
New-Item $Out -ItemType Directory -Force | Out-Null

$Classified = Join-Path $DataRoot "classified\classified_results.jsonl"
$RawRoot = Join-Path $DataRoot "raw_runs"
$StatusFile = Join-Path $DataRoot "status\latest_status.json"

if (-not (Test-Path $Classified)) {
    Write-Host "ERROR: classified_results.jsonl not found:" -ForegroundColor Red
    Write-Host $Classified -ForegroundColor Red
    Write-Host "Run at least one successful monitoring cycle first." -ForegroundColor Yellow
    exit 3
}

if (Test-Path $StatusFile) {
    Copy-Item $StatusFile (Join-Path $Out "01_latest_status.json") -Force
}

$AllRows = @(
    Get-Content $Classified -Encoding UTF8 |
    ForEach-Object {
        $line = $_
        if (-not [string]::IsNullOrWhiteSpace($line)) {
            try { $line | ConvertFrom-Json } catch {}
        }
    }
)

function Get-RecordScopeDate($row) {
    foreach ($name in @("first_seen_time", "engagement_refresh_time", "publish_time")) {
        if ($row.PSObject.Properties.Name -contains $name) {
            $value = [string]$row.$name
            if (-not [string]::IsNullOrWhiteSpace($value)) {
                try { return ([datetimeoffset]::Parse($value)).ToLocalTime().ToString("yyyy-MM-dd") } catch {}
                try { return ([datetime]::Parse($value)).ToString("yyyy-MM-dd") } catch {}
            }
        }
    }
    return ""
}

if ($Cumulative) {
    $Rows = @($AllRows)
} else {
    $Rows = @($AllRows | Where-Object { (Get-RecordScopeDate $_) -eq $TargetDateText })
}

# The scoped classified JSONL is what belongs in the daily handoff package.
$ScopedClassified = Join-Path $Out "01_classified_results_scope.jsonl"
$Rows | ForEach-Object { $_ | ConvertTo-Json -Depth 100 -Compress } |
    Set-Content $ScopedClassified -Encoding UTF8

$Comments = @($Rows | Where-Object { [string]$_.record_type -eq "comment" })
$Contents = @($Rows | Where-Object { [string]$_.record_type -ne "comment" })
$Candidates = @($Comments | Where-Object { [string]$_.status -eq "problematic" })
$ContentCandidates = @($Contents | Where-Object { [string]$_.status -eq "problematic" })

$CommonCols = @(
    "platform","record_type","sample_id","content_id","comment_id",
    "parent_comment_id","root_comment_id","comment_level",
    "publish_time","first_seen_time","author","content","context","url",
    "ip_location","likes","comments","shares","views","favorites","danmaku","coins",
    "status","type","tri_class","classification_state","classification_method",
    "source_keyword","language","source_type"
)

$ReviewCols = @(
    "platform","record_type","sample_id","content_id","comment_id",
    "parent_comment_id","root_comment_id","comment_level",
    "publish_time","first_seen_time","author","content","context","url",
    "ip_location","likes","comments","shares","views",
    "status","type","tri_class",
    @{Name="manual_label";Expression={""}},
    @{Name="manual_note";Expression={""}},
    @{Name="reviewer";Expression={""}},
    @{Name="reviewed_at";Expression={""}}
)

$Comments |
    Select-Object -Property $CommonCols |
    Export-Csv (Join-Path $Out "02_全部评论原文.csv") -NoTypeInformation -Encoding UTF8

$Contents |
    Select-Object -Property $CommonCols |
    Export-Csv (Join-Path $Out "02_全部发布内容.csv") -NoTypeInformation -Encoding UTF8

$Candidates |
    Select-Object -Property $ReviewCols |
    Export-Csv (Join-Path $Out "03_problematic评论候选_人工复核.csv") -NoTypeInformation -Encoding UTF8

$ContentCandidates |
    Select-Object -Property $ReviewCols |
    Export-Csv (Join-Path $Out "03_problematic发布内容候选_人工复核.csv") -NoTypeInformation -Encoding UTF8

$Candidates |
    Group-Object type |
    Sort-Object Count -Descending |
    Select-Object @{Name="type";Expression={$_.Name}}, Count |
    Export-Csv (Join-Path $Out "04_problematic类型统计.csv") -NoTypeInformation -Encoding UTF8

$Candidates |
    Where-Object { [string]$_.type -eq "discriminatory_expression" } |
    Select-Object -Property $ReviewCols |
    Export-Csv (Join-Path $Out "05_优先复核_歧视贬损候选.csv") -NoTypeInformation -Encoding UTF8

$Candidates |
    Where-Object { [string]$_.type -eq "criticism" } |
    Select-Object -Property $ReviewCols |
    Export-Csv (Join-Path $Out "06_批评类候选.csv") -NoTypeInformation -Encoding UTF8

$Candidates |
    Where-Object { [string]$_.type -eq "skepticism" } |
    Select-Object -Property $ReviewCols |
    Export-Csv (Join-Path $Out "07_质疑类候选.csv") -NoTypeInformation -Encoding UTF8

$RawFilesCopied = 0
if (-not $NoRawCopy -and (Test-Path $RawRoot)) {
    $RawCommentOut = Join-Path $Out "raw_comment_jsonl"
    $RawContentOut = Join-Path $Out "raw_content_jsonl"
    New-Item $RawCommentOut -ItemType Directory -Force | Out-Null
    New-Item $RawContentOut -ItemType Directory -Force | Out-Null

    $commentIndex = 0
    $contentIndex = 0
    $RawFiles = @()
    if ($Cumulative) {
        $RawFiles = @(Get-ChildItem $RawRoot -Recurse -File -Filter *.jsonl -ErrorAction SilentlyContinue)
    } else {
        $DayCycles = @(Get-ChildItem $RawRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "$TargetDateCompact*" })
        foreach ($cycle in $DayCycles) {
            $RawFiles += @(Get-ChildItem $cycle.FullName -Recurse -File -Filter *.jsonl -ErrorAction SilentlyContinue)
        }
    }

    $RawFiles | ForEach-Object {
        $nameLower = $_.Name.ToLowerInvariant()
        if ($nameLower -match "comment") {
            $commentIndex++
            Copy-Item $_.FullName (Join-Path $RawCommentOut ("{0:D5}_{1}" -f $commentIndex, $_.Name)) -Force
            $RawFilesCopied++
        } elseif ($nameLower -match "content|search|post|video|note|aweme") {
            $contentIndex++
            Copy-Item $_.FullName (Join-Path $RawContentOut ("{0:D5}_{1}" -f $contentIndex, $_.Name)) -Force
            $RawFilesCopied++
        }
    }
}

$Readme = @"
平台：$PlatformName ($Platform)
导出时间：$(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
导出范围：$ScopeLabel（默认按 first_seen_time 统计当天新发现记录；-Cumulative 可导出累计）
配置文件：$Config
真实数据目录：$DataRoot
分类结果：$Classified
发布内容记录数：$($Contents.Count)
评论记录数：$($Comments.Count)
模型 problematic 评论候选数：$($Candidates.Count)
模型 problematic 发布内容候选数：$($ContentCandidates.Count)
复制原始 JSONL 文件数：$RawFilesCopied

【重要说明】
1. problematic 只是“需要人工复核的问题候选”，不能直接等同于最终“非支持”。
2. manual_label 仅填写以下四类：
   support              明确支持、认可、积极评价
   neutral              中性陈述、信息缺口、咨询、普通疑问、一般质疑/批评但无明确反对
   non_support          明确反对/否定宣传周本身，或明确贬损、排斥、歧视相关群体
   needs_second_review  语义不清、反讽、上下文不足，需二次复核
3. 复核时必须同时查看 content（原话）和 context（母帖/视频/主题帖上下文）。
4. 不要为了“对上模型数字”而判定；以原话真实语义为准。
5. 禁止发送 Cookie、API Key、浏览器登录态、账号密码等敏感信息。
"@
$Readme | Set-Content (Join-Path $Out "00_先看这个_数据说明.txt") -Encoding UTF8

$Summary = [PSCustomObject]@{
    platform = $Platform
    platform_name = $PlatformName
    exported_at = (Get-Date).ToString("s")
    scope = $ScopeLabel
    cumulative = [bool]$Cumulative
    data_root = $DataRoot
    classified_file = $Classified
    content_records = $Contents.Count
    comment_records = $Comments.Count
    problematic_comment_candidates = $Candidates.Count
    problematic_content_candidates = $ContentCandidates.Count
    raw_files_copied = $RawFilesCopied
}
$Summary | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $Out "00_export_summary.json") -Encoding UTF8

Compress-Archive -Path (Join-Path $Out "*") -DestinationPath $Zip -Force

Write-Host ""
Write-Host "=== Export completed ===" -ForegroundColor Green
Write-Host "Platform: $PlatformName" -ForegroundColor Cyan
Write-Host "DataRoot: $DataRoot" -ForegroundColor Cyan
Write-Host "Comments: $($Comments.Count)" -ForegroundColor Cyan
Write-Host "Problematic comment candidates: $($Candidates.Count)" -ForegroundColor Cyan
Write-Host "Problematic content candidates: $($ContentCandidates.Count)" -ForegroundColor Cyan
Write-Host "ZIP: $Zip" -ForegroundColor Green
Write-Host ""
Write-Host "Send the ZIP to the coordinator. If manual review is requested, fill the 03_problematic*_人工复核.csv file(s) and send those CSV files too." -ForegroundColor Yellow

Start-Process explorer.exe $OutputRoot
