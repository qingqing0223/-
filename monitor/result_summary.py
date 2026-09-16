from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
from typing import Iterable

from pipeline.language_detector import is_minority_language


PLATFORM_CODES = ("xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu")


def _read_json(path: Path, default=None):
    if default is None:
        default = {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
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
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
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


def discover_data_roots(base_data_root: Path, include_multilingual: bool = True) -> list[Path]:
    """Discover formal per-platform roots without including smoke/region test roots."""
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
    """Build a privacy-safe aggregate scoped to the formal monitoring start time."""
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
            key = str(row.get("dedupe_key") or f"{row.get('platform','')}:{row.get('sample_id','')}")
            if key:
                latest_rows[key] = row

    platform_counts = Counter()
    language_counts = Counter()
    minority_language_counts = Counter()
    region_counts = Counter()
    status_counts = Counter()
    type_counts = Counter()
    source_type_counts = Counter()
    record_type_counts = Counter()
    engagement = Counter()
    latest_seen = ""

    for row in latest_rows.values():
        platform = str(row.get("platform") or "unknown")
        language = str(row.get("language") or "未知")
        region = str(row.get("ip_location") or "").strip()
        status = str(row.get("status") or "unknown")
        type_ = str(row.get("type") or "null")
        source_type = str(row.get("source_type") or "未分类")
        record_type = str(row.get("record_type") or "unknown")

        platform_counts[platform] += 1
        language_counts[language] += 1
        if is_minority_language(language):
            minority_language_counts[language] += 1
        if region:
            region_counts[region] += 1
        status_counts[status] += 1
        type_counts[type_] += 1
        source_type_counts[source_type] += 1
        record_type_counts[record_type] += 1

        for key in ("likes", "comments", "shares", "views", "favorites", "danmaku", "coins"):
            engagement[key] += int(row.get(key) or 0)

        first_seen = str(row.get("first_seen_time") or "")
        refresh_seen = str(row.get("engagement_refresh_time") or "")
        candidate = max(first_seen, refresh_seen)
        if candidate > latest_seen:
            latest_seen = candidate

    total = len(latest_rows)
    region_total = sum(region_counts.values())
    minority_total = sum(minority_language_counts.values())
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    return {
        "schema_version": 3,
        "generated_at": generated_at,
        "monitoring_start_time": monitoring_start_time,
        "latest_seen_time": latest_seen,
        "privacy": "aggregate_only_no_raw_text_no_account_no_url",
        "totals": {
            "unique_records": total,
            "filtered_before_start_from_existing_output": filtered_existing,
            "region_records": region_total,
            "region_coverage_rate": round(region_total / total, 4) if total else 0.0,
            "minority_language_records": minority_total,
            "minority_language_rate": round(minority_total / total, 4) if total else 0.0,
            "likes": engagement["likes"],
            "comments": engagement["comments"],
            "shares": engagement["shares"],
            "views": engagement["views"],
            "favorites": engagement["favorites"],
            "danmaku": engagement["danmaku"],
            "coins": engagement["coins"],
        },
        "platforms": dict(platform_counts.most_common()),
        "languages": dict(language_counts.most_common()),
        "minority_languages": dict(minority_language_counts.most_common()),
        "regions": dict(region_counts.most_common()),
        "v2_status": dict(status_counts.most_common()),
        "v2_type": dict(type_counts.most_common()),
        "source_types": dict(source_type_counts.most_common()),
        "record_types": dict(record_type_counts.most_common()),
        "runtime": runtime,
    }


def write_summary(repo_root: Path, summary: dict, result_date: str = "") -> dict:
    date_key = (result_date or str(summary.get("generated_at") or datetime.now().isoformat())[:10]).strip()
    day_root = repo_root / "results" / date_key
    summary_dir = day_root / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)

    latest = summary_dir / "latest_summary.json"
    latest.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    snapshot = summary_dir / "summary.json"
    snapshot.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"latest": str(latest), "summary": str(snapshot), "date_root": str(day_root)}
