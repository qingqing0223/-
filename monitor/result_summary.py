from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
from typing import Iterable

from pipeline.language_detector import is_minority_language


PLATFORM_CODES = (
    "xhs", "dy", "ks", "bili", "wb", "toutiao", "zhihu",
    "wechat_mp", "wechat_channels",
)

# Two Douyin videos were manually reviewed and confirmed unrelated to this
# promotion-week monitoring topic.  Match on the public engagement snapshot
# plus platform/type rather than account name, so future relevant posts from
# the same publishers are not suppressed.
REPORTING_EXCLUDED_SIGNATURES = {
    ("dy", "video", 46431, 50, 900),
    ("dy", "video", 6288, 48, 119),
}

# Manually reviewed Bilibili comments excluded from public GitHub reporting.
# Raw/local records remain preserved for audit and review.
REPORTING_EXCLUDED_RECORD_IDS = {
    ("bili", "comment", "314288237793"),
    ("bili", "comment", "317841315680"),
}


def _is_reporting_excluded(row: dict) -> bool:
    platform = str(row.get("platform") or "")
    record_type = str(row.get("record_type") or "")
    record_id = str(row.get("comment_id") or row.get("sample_id") or "")

    if (platform, record_type, record_id) in REPORTING_EXCLUDED_RECORD_IDS:
        return True

    signature = (
        platform,
        record_type,
        int(row.get("likes") or 0),
        int(row.get("comments") or 0),
        int(row.get("shares") or 0),
    )
    return signature in REPORTING_EXCLUDED_SIGNATURES


def _read_json(path: Path, default=None):
    if default is None:
        default = {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _iter_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                yield row


def _parse_scope_time(value, default_tz=None):
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    dt = None
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        # Some platform exports use non-zero-padded dates such as
        # "2026-7-16 09:35".  fromisoformat rejects these, so fall back to
        # strptime before deciding the timestamp is unparseable.
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
        ):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except Exception:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None and default_tz is not None:
        dt = dt.replace(tzinfo=default_tz)
    return dt


def _row_before_start(row: dict, monitoring_start_time: str) -> bool:
    start = _parse_scope_time(monitoring_start_time)
    if start is None:
        return False
    published = _parse_scope_time(row.get("publish_time"), default_tz=start.tzinfo)
    if published is None:
        return False
    return published < start


def _canonical_status_type(status: str, type_: str | None) -> tuple[str, str]:
    """Map the retired v2.1 neutral/null pair to the v2.2 hierarchy.

    Historical classified JSONL is immutable.  Canonicalizing only while
    producing summaries keeps old records usable without presenting ``neutral``
    as a current L1 value.
    """
    status = str(status or "").strip()
    type_ = str(type_ or "").strip()
    if status == "neutral" and type_ in {"", "null"}:
        return "attention", "neutral"
    return status, type_ or "null"


def _attitude_bucket(status: str, type_: str) -> str:
    """Reporting bucket derived from the fixed v2 taxonomy.

    L1 attention is named "中性信息". Its neutral subtype enters the
    neutral reporting bucket, while information gaps and consultations retain a
    separate attention bucket. Neither is treated as negative.
    """
    status = str(status or "").strip()
    type_ = str(type_ or "").strip()
    if status == "normal" and type_ == "support":
        return "support"
    if status == "neutral":  # legacy v2.1 compatibility
        return "neutral"
    if status == "problematic":
        return "non_support"
    if status == "attention":
        return "neutral" if type_ == "neutral" else "attention"
    return "unknown"


def _tri_class_bucket(status: str) -> str:
    """Exact three-class review label derived from the fixed v2.2 L1 taxonomy."""
    status = str(status or "").strip()
    if status == "normal":
        return "support"
    if status in {"attention", "neutral"}:  # legacy neutral -> neutral
        return "neutral"
    if status == "problematic":
        return "non_support"
    return "unknown"


def discover_data_roots(base_data_root: Path, include_multilingual: bool = True) -> list[Path]:
    """Discover formal per-platform roots without smoke/region test roots."""
    parent = base_data_root.parent
    base = base_data_root.name
    roots = []
    for code in PLATFORM_CODES:
        p = parent / f"{base}_{code}"
        if p.exists():
            roots.append(p)
    if include_multilingual:
        for code in PLATFORM_CODES:
            p = parent / f"{base}_multilingual_{code}"
            if p.exists():
                roots.append(p)
    return roots


def _merge_status(root: Path) -> dict:
    status = _read_json(root / "status" / "latest_status.json", {})
    runs = status.get("platform_runs") or []
    run = runs[0] if runs else {}
    ingest = (status.get("ingest") or [{}])[0]
    dashboard = status.get("dashboard_push") or {}
    input_files = [str(p) for p in (ingest.get("input_files") or [])]
    comment_input_file_count = sum(1 for p in input_files if "comment" in Path(p).name.lower())
    return {
        "data_root": str(root),
        "cycle_finished_at": status.get("cycle_finished_at") or "",
        "crawler_status": run.get("status") or "unknown",
        "crawler_state": run.get("state") or "unknown",
        "return_code": run.get("return_code"),
        "duration_seconds": run.get("duration_seconds"),
        "new_records": ingest.get("new_records", 0),
        "filtered_before_start": ingest.get("filtered_before_start", 0),
        "classified_records": ingest.get("classified_records", 0),
        "ingest_comments": bool(ingest.get("ingest_comments", False)),
        "input_file_count": len(input_files),
        "comment_input_file_count": comment_input_file_count,
        "region_records": ingest.get("region_records", 0),
        "region_rate": ingest.get("region_rate", 0.0),
        "minority_language_records": ingest.get("minority_language_records", 0),
        "language_counts": ingest.get("language_counts") or {},
        "dashboard_ok": dashboard.get("ok"),
        "dashboard_sent": dashboard.get("sent", 0),
        "dashboard_inserted": dashboard.get("inserted", 0),
        "dashboard_skipped": dashboard.get("skipped", 0),
        "outbox_after": dashboard.get("outbox_after"),
    }


def build_summary(data_roots: Iterable[Path], monitoring_start_time: str = "") -> dict:
    """Build an aggregate suitable for GitHub synchronization and reporting.

    Raw text and URLs are never included. Public publisher account display names
    are included only as aggregate account statistics so the daily report can name
    which public accounts posted relevant material.
    """
    latest_rows: dict[str, dict] = {}
    runtime = []
    filtered_existing = 0

    for root in data_roots:
        runtime.append(_merge_status(root))
        classified = root / "classified" / "classified_results.jsonl"
        for row in _iter_jsonl(classified) or []:
            if _row_before_start(row, monitoring_start_time):
                filtered_existing += 1
                continue
            if _is_reporting_excluded(row):
                continue
            key = str(row.get("dedupe_key") or f"{row.get('platform','')}:{row.get('sample_id','')}")
            if key:
                latest_rows[key] = row

    platform_counts = Counter()
    language_counts = Counter()
    minority_language_counts = Counter()
    region_counts = Counter()
    content_region_counts = Counter()
    comment_region_counts_by_name = Counter()
    status_counts = Counter()
    type_counts = Counter()
    attitude_counts = Counter()
    tri_class_counts = Counter()
    comment_status_counts = Counter()
    comment_type_counts = Counter()
    comment_attitude_counts = Counter()
    comment_tri_class_counts = Counter()
    source_type_counts = Counter()
    record_type_counts = Counter()
    keyword_counts = Counter()
    engagement = Counter()
    platform_attitude: dict[str, Counter] = {}
    platform_tri_class: dict[str, Counter] = {}
    account_stats: dict[str, dict] = {}
    comment_author_keys: set[str] = set()
    spreading_account_keys: set[str] = set()
    latest_seen = ""

    comment_records = 0
    root_comment_records = 0
    reply_comment_records = 0
    parent_linked_comment_records = 0
    comment_region_records = 0
    video_records = 0
    video_with_asr = 0
    video_with_ocr = 0
    video_multimodal_complete = 0

    for row in latest_rows.values():
        platform = str(row.get("platform") or "unknown")
        language = str(row.get("language") or "未知")
        region = str(row.get("ip_location") or "").strip()
        status, type_ = _canonical_status_type(row.get("status") or "unknown", row.get("type"))
        source_type = str(row.get("source_type") or "未分类")
        record_type = str(row.get("record_type") or "unknown")
        keyword = str(row.get("source_keyword") or "").strip()
        attitude = _attitude_bucket(status, type_)
        tri_class = _tri_class_bucket(status)

        platform_counts[platform] += 1
        language_counts[language] += 1
        if is_minority_language(language):
            minority_language_counts[language] += 1
        if region:
            region_counts[region] += 1
        status_counts[status] += 1
        type_counts[type_] += 1
        attitude_counts[attitude] += 1
        tri_class_counts[tri_class] += 1
        source_type_counts[source_type] += 1
        record_type_counts[record_type] += 1
        if keyword:
            keyword_counts[keyword] += 1
        platform_attitude.setdefault(platform, Counter())[attitude] += 1
        platform_tri_class.setdefault(platform, Counter())[tri_class] += 1

        if record_type == "comment":
            comment_records += 1
            comment_status_counts[status] += 1
            comment_type_counts[type_] += 1
            comment_attitude_counts[attitude] += 1
            comment_tri_class_counts[tri_class] += 1
            if region:
                comment_region_records += 1
                comment_region_counts_by_name[region] += 1
            level = int(row.get("comment_level") or 0)
            parent_id = str(row.get("parent_comment_id") or "").strip()
            if level >= 2 or parent_id:
                reply_comment_records += 1
            else:
                root_comment_records += 1
            if parent_id:
                parent_linked_comment_records += 1
            author_key = str(row.get("author_id") or row.get("author") or "").strip()
            if author_key:
                comment_author_keys.add(author_key)
                spreading_account_keys.add(f"{platform}:{author_key}")
        else:
            if region:
                content_region_counts[region] += 1
            public_author = str(row.get("author") or "").strip()
            public_author_id = str(row.get("author_id") or "").strip()
            public_author_key = public_author_id or public_author
            if public_author_key:
                spreading_account_keys.add(f"{platform}:{public_author_key}")
            if public_author:
                stat = account_stats.setdefault(public_author, {
                    "account": public_author,
                    "platforms": Counter(),
                    "records": 0,
                    "posts": 0,
                    "videos": 0,
                    "attitude": Counter(),
                    "regions": Counter(),
                    "likes": 0,
                    "comments": 0,
                    "shares": 0,
                    "views": 0,
                    "favorites": 0,
                    "danmaku": 0,
                    "coins": 0,
                })
                stat["platforms"][platform] += 1
                stat["records"] += 1
                if record_type == "video":
                    stat["videos"] += 1
                elif record_type == "post":
                    stat["posts"] += 1
                stat["attitude"][attitude] += 1
                if region:
                    stat["regions"][region] += 1
                for k in ("likes", "comments", "shares", "views", "favorites", "danmaku", "coins"):
                    stat[k] += int(row.get(k) or 0)

        if record_type == "video":
            video_records += 1
            has_asr = bool(str(row.get("asr_text") or "").strip())
            has_ocr = bool(str(row.get("ocr_text") or "").strip())
            if has_asr:
                video_with_asr += 1
            if has_ocr:
                video_with_ocr += 1
            if has_asr and has_ocr:
                video_multimodal_complete += 1

        for key in ("likes", "comments", "shares", "views", "favorites", "danmaku", "coins"):
            engagement[key] += int(row.get(key) or 0)

        first_seen = str(row.get("first_seen_time") or "")
        refresh_seen = str(row.get("engagement_refresh_time") or "")
        candidate = max(first_seen, refresh_seen)
        if candidate > latest_seen:
            latest_seen = candidate

    public_account_stats = []
    for name, stat in account_stats.items():
        public_account_stats.append({
            "account": name,
            "platforms": dict(stat["platforms"].most_common()),
            "records": stat["records"],
            "posts": stat["posts"],
            "videos": stat["videos"],
            "attitude": dict(stat["attitude"].most_common()),
            "regions": dict(stat["regions"].most_common()),
            "engagement": {
                "likes": stat["likes"],
                "comments": stat["comments"],
                "shares": stat["shares"],
                "views": stat["views"],
                "favorites": stat["favorites"],
                "danmaku": stat["danmaku"],
                "coins": stat["coins"],
            },
        })
    public_account_stats.sort(key=lambda x: (-int(x["records"]), str(x["account"])))
    account_limit = 200
    accounts_total = len(public_account_stats)
    public_account_stats = public_account_stats[:account_limit]

    total = len(latest_rows)
    content_records = max(0, total - comment_records)
    region_total = sum(region_counts.values())
    minority_total = sum(minority_language_counts.values())
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    interaction_total = (
        int(engagement["likes"])
        + int(engagement["comments"])
        + int(engagement["shares"])
        + int(engagement["favorites"])
    )
    generated_dt = datetime.fromisoformat(generated_at)
    statistics_time = generated_dt.replace(minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
    overall_trend_current = {
        "statistics_time": statistics_time,
        "information_total": total,
        "published_content_count": content_records,
        "comment_reply_count": comment_records,
        "spreading_account_count": len(spreading_account_keys),
        "views": int(engagement["views"]),
        "interaction_total": interaction_total,
        "likes": int(engagement["likes"]),
        "comments": int(engagement["comments"]),
        "shares": int(engagement["shares"]),
        "favorites": int(engagement["favorites"]),
    }

    return {
        "schema_version": 7,
        "generated_at": generated_at,
        "monitoring_start_time": monitoring_start_time,
        "latest_seen_time": latest_seen,
        "privacy": "aggregate_no_raw_text_no_url_public_publisher_account_stats",
        "totals": {
            "unique_records": total,
            "filtered_before_start_from_existing_output": filtered_existing,
            "region_records": region_total,
            "region_coverage_rate": round(region_total / total, 4) if total else 0.0,
            "minority_language_records": minority_total,
            "minority_language_rate": round(minority_total / total, 4) if total else 0.0,
            "comment_records": comment_records,
            "root_comment_records": root_comment_records,
            "reply_comment_records": reply_comment_records,
            "parent_linked_comment_records": parent_linked_comment_records,
            "comment_parent_link_rate": round(parent_linked_comment_records / reply_comment_records, 4) if reply_comment_records else 0.0,
            "comment_region_records": comment_region_records,
            "comment_region_coverage_rate": round(comment_region_records / comment_records, 4) if comment_records else 0.0,
            "unique_comment_authors": len(comment_author_keys),
            "public_publisher_accounts": accounts_total,
            "spreading_accounts": len(spreading_account_keys),
            "published_content_records": content_records,
            "likes": engagement["likes"],
            "comments": engagement["comments"],
            "shares": engagement["shares"],
            "views": engagement["views"],
            "favorites": engagement["favorites"],
            "danmaku": engagement["danmaku"],
            "coins": engagement["coins"],
        },
        "platforms": dict(platform_counts.most_common()),
        "platform_attitude": {k: dict(v.most_common()) for k, v in platform_attitude.items()},
        "platform_tri_class": {k: dict(v.most_common()) for k, v in platform_tri_class.items()},
        "languages": dict(language_counts.most_common()),
        "minority_languages": dict(minority_language_counts.most_common()),
        "regions": dict(region_counts.most_common()),
        "content_regions": dict(content_region_counts.most_common()),
        "comment_regions": dict(comment_region_counts_by_name.most_common()),
        "v2_status": dict(status_counts.most_common()),
        "v2_type": dict(type_counts.most_common()),
        "attitude": dict(attitude_counts.most_common()),
        "tri_class": dict(tri_class_counts.most_common()),
        "comment_v2_status": dict(comment_status_counts.most_common()),
        "comment_v2_type": dict(comment_type_counts.most_common()),
        "comment_attitude": dict(comment_attitude_counts.most_common()),
        "comment_tri_class": dict(comment_tri_class_counts.most_common()),
        "source_types": dict(source_type_counts.most_common()),
        "record_types": dict(record_type_counts.most_common()),
        "keywords": dict(keyword_counts.most_common()),
        "video_analysis": {
            "video_records": video_records,
            "with_asr": video_with_asr,
            "with_ocr": video_with_ocr,
            "multimodal_complete": video_multimodal_complete,
            "multimodal_completion_rate": round(video_multimodal_complete / video_records, 4) if video_records else 0.0,
        },
        "public_account_stats": public_account_stats,
        "public_account_stats_total": accounts_total,
        "public_account_stats_truncated": accounts_total > account_limit,
        "overall_trend_current": overall_trend_current,
        "runtime": runtime,
    }


def _upsert_hourly_overall_trend(day_root: Path, trend: dict) -> Path:
    """Persist Tech Design V3 Table 9 as one replaceable snapshot per hour."""
    trend_dir = day_root / "trend"
    trend_dir.mkdir(parents=True, exist_ok=True)
    path = trend_dir / "overall_hourly.jsonl"
    key = str(trend.get("statistics_time") or "")
    existing: list[dict] = []
    if path.exists():
        existing = list(_iter_jsonl(path) or [])
    replaced = False
    output: list[dict] = []
    for row in existing:
        if str(row.get("statistics_time") or "") == key:
            if not replaced:
                output.append(dict(trend))
                replaced = True
            continue
        output.append(row)
    if not replaced:
        output.append(dict(trend))
    output.sort(key=lambda row: str(row.get("statistics_time") or ""))
    with path.open("w", encoding="utf-8") as f:
        for row in output:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def write_summary(repo_root: Path, summary: dict, result_date: str = "") -> dict:
    date_key = (result_date or str(summary.get("generated_at") or datetime.now().isoformat())[:10]).strip()
    day_root = repo_root / "results" / date_key
    summary_dir = day_root / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)

    latest = summary_dir / "latest_summary.json"
    latest.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    snapshot = summary_dir / "summary.json"
    snapshot.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    trend_path = _upsert_hourly_overall_trend(
        day_root,
        dict(summary.get("overall_trend_current") or {}),
    )
    return {
        "latest": str(latest),
        "summary": str(snapshot),
        "overall_hourly_trend": str(trend_path),
        "date_root": str(day_root),
    }
