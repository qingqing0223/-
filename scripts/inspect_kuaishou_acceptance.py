from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor.result_summary import build_summary


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _platform_root(cfg: dict) -> Path:
    base = Path(cfg["data_root"])
    if base.name.endswith("_ks"):
        return base
    return base.parent / f"{base.name}_ks"


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect Kuaishou collection against the PPT acceptance fields.")
    ap.add_argument("--config", default=str(ROOT / "config" / "monitoring.local.json"))
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = _load(cfg_path)
    if not cfg:
        print(json.dumps({"ok": False, "error": "config_not_readable", "config": str(cfg_path)}, ensure_ascii=False, indent=2))
        return 2

    root = _platform_root(cfg)
    status = _load(root / "status" / "latest_status.json")
    summary = build_summary([root], monitoring_start_time=str(cfg.get("monitoring_start_time") or "")) if root.exists() else {}
    totals = summary.get("totals") or {}
    runtime = (summary.get("runtime") or [{}])[-1]
    source_types = summary.get("source_types") or {}

    run = (status.get("platform_runs") or [{}])[0]
    ingest = (status.get("ingest") or [{}])[0]

    root_comments = int(totals.get("root_comment_records") or 0)
    replies = int(totals.get("reply_comment_records") or 0)
    linked = int(totals.get("parent_linked_comment_records") or 0)
    comment_records = int(totals.get("comment_records") or 0)
    comment_region = int(totals.get("comment_region_records") or 0)
    region_records = int(totals.get("region_records") or 0)
    unique_records = int(totals.get("unique_records") or 0)

    parent_integrity = round(linked / replies, 4) if replies else 1.0
    comment_region_rate = round(comment_region / comment_records, 4) if comment_records else 0.0
    region_rate = round(region_records / unique_records, 4) if unique_records else 0.0

    checks = {
        "content_collected": unique_records > 0,
        "source_type_classification_present": bool(source_types),
        "first_level_comments_present": root_comments > 0,
        "nested_replies_present": replies > 0,
        "nested_parent_links_complete": (replies == 0) or (linked == replies),
        "comment_public_ip_region_present": comment_region > 0,
        "content_public_ip_region_present": region_records > 0,
        "comment_ingest_enabled": bool(runtime.get("ingest_comments", False) or ingest.get("ingest_comments", False)),
    }

    result = {
        "ok": bool(checks["content_collected"] and checks["comment_ingest_enabled"]),
        "platform": "ks",
        "config": str(cfg_path),
        "data_root": str(root),
        "latest_cycle": {
            "finished_at": status.get("cycle_finished_at"),
            "crawler_state": run.get("state") or runtime.get("crawler_state"),
            "duration_seconds": run.get("duration_seconds") or runtime.get("duration_seconds"),
            "realtime_target_seconds": status.get("realtime_target_seconds", 300),
            "realtime_cycle_within_target": status.get("realtime_cycle_within_target"),
            "content_rows": run.get("content_row_count", 0),
            "comment_rows": run.get("comment_row_count", 0),
            "detail_recovery_candidates": run.get("detail_recovery_candidates", 0),
            "detail_recovery_batches": run.get("detail_recovery_batches", 0),
            "deep_queue_pending": run.get("deep_queue_pending", 0),
        },
        "ppt_fields": {
            "videos_or_posts": unique_records - comment_records,
            "source_type_counts": source_types,
            "first_level_comments": root_comments,
            "nested_replies": replies,
            "parent_linked_replies": linked,
            "parent_integrity_rate": parent_integrity,
            "comment_public_ip_region_records": comment_region,
            "comment_public_ip_region_rate": comment_region_rate,
            "all_public_ip_region_records": region_records,
            "all_public_ip_region_rate": region_rate,
            "comment_regions": summary.get("comment_regions") or {},
            "content_regions": summary.get("content_regions") or {},
        },
        "pipeline": {
            "raw_comment_rows": ingest.get("raw_comment_rows", 0),
            "normalized_comment_records": ingest.get("normalized_comment_records", 0),
            "classified_comment_records": ingest.get("classified_comment_records", 0),
            "duplicate_skipped": ingest.get("duplicate_skipped", 0),
            "filtered_before_start": ingest.get("filtered_before_start", 0),
        },
        "checks": checks,
        "source_type_note": (
            "source_type is the monitoring system's reporting classification (heuristic/LLM from public account name/content), "
            "not a claim that Kuaishou supplied an official verification badge unless such a public field is separately present in raw data."
        ),
        "ip_note": "Only platform-displayed coarse IP-location labels are retained; real IP addresses and precise locations are not collected.",
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
