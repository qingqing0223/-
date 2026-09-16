from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
from typing import Iterable

from pipeline.language_detector import is_minority_language


PLATFORM_CODES = ("wb", "xhs", "dy", "ks")


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
        "return_code": run.get("return_code"),
        "duration_seconds": run.get("duration_seconds"),
        "new_records": ingest.get("new_records", 0),
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


def build_summary(data_roots: Iterable[Path]) -> dict:
    """Build a privacy-safe aggregate. No raw text, account names or URLs are emitted."""
    seen = set()
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
    runtime = []

    for root in data_roots:
        runtime.append(_merge_status(root))
        classified = root / "classified" / "classified_results.jsonl"
        for row in _iter_jsonl(classified) or []:
            key = str(row.get("dedupe_key") or f"{row.get('platform','')}:{row.get('sample_id','')}")
            if not key or key in seen:
                continue
            seen.add(key)

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

            engagement["likes"] += int(row.get("likes") or 0)
            engagement["comments"] += int(row.get("comments") or 0)
            engagement["shares"] += int(row.get("shares") or 0)

            first_seen = str(row.get("first_seen_time") or "")
            if first_seen > latest_seen:
                latest_seen = first_seen

    total = len(seen)
    region_total = sum(region_counts.values())
    minority_total = sum(minority_language_counts.values())
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "latest_seen_time": latest_seen,
        "privacy": "aggregate_only_no_raw_text_no_account_no_url",
        "totals": {
            "unique_records": total,
            "region_records": region_total,
            "region_coverage_rate": round(region_total / total, 4) if total else 0.0,
            "minority_language_records": minority_total,
            "minority_language_rate": round(minority_total / total, 4) if total else 0.0,
            "likes": engagement["likes"],
            "comments": engagement["comments"],
            "shares": engagement["shares"],
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


def write_summary(repo_root: Path, summary: dict) -> dict:
    results_dir = repo_root / "results"
    daily_dir = results_dir / "daily"
    results_dir.mkdir(parents=True, exist_ok=True)
    daily_dir.mkdir(parents=True, exist_ok=True)

    latest = results_dir / "latest_summary.json"
    latest.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    date_key = str(summary.get("generated_at") or datetime.now().isoformat())[:10]
    daily = daily_dir / f"{date_key}.json"
    daily.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"latest": str(latest), "daily": str(daily)}
