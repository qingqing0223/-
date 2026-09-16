from __future__ import annotations

import argparse
from collections import Counter
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


def _iter_jsonl(path: Path):
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as f:
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
    except Exception:
        return


def _platform_root(cfg: dict) -> Path:
    base = Path(cfg["data_root"])
    if base.name.endswith("_ks"):
        return base
    return base.parent / f"{base.name}_ks"


def _latest_cycle(root: Path) -> Path | None:
    raw_root = root / "raw_runs"
    if not raw_root.exists():
        return None
    cycles = sorted((p for p in raw_root.iterdir() if p.is_dir()), key=lambda p: p.name)
    return cycles[-1] if cycles else None


def _first(row: dict, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _region(row: dict) -> str:
    value = _first(row, "ip_location", "ip_region", "ip_label", "region", "region_name", "province")
    if value in (None, ""):
        for key in ("user", "user_info", "author", "member"):
            obj = row.get(key)
            if isinstance(obj, dict):
                value = _first(obj, "ip_location", "ip_region", "ip_label", "region", "region_name", "province")
                if value not in (None, ""):
                    break
    text = str(value or "").strip()
    if not text:
        return ""
    # Safety: this acceptance inspector only reports platform-displayed coarse labels.
    if any(ch.isdigit() for ch in text) and ("." in text or ":" in text):
        return ""
    return text


def _raw_acceptance(root: Path) -> dict:
    cycle = _latest_cycle(root)
    if cycle is None:
        return {
            "available": False,
            "cycle": "",
            "content_rows": 0,
            "comment_rows": 0,
            "first_level_comments": 0,
            "nested_replies": 0,
            "parent_linked_replies": 0,
            "parent_integrity_rate": 1.0,
            "comment_public_ip_region_records": 0,
            "content_public_ip_region_records": 0,
            "comment_regions": {},
            "content_regions": {},
            "content_comment_count_positive": 0,
            "content_files": [],
            "comment_files": [],
        }

    jsonl_files = sorted(cycle.rglob("*.jsonl"))
    content_files = [p for p in jsonl_files if "content" in p.name.lower()]
    comment_files = [p for p in jsonl_files if "comment" in p.name.lower()]

    content_rows = 0
    content_comment_count_positive = 0
    content_regions = Counter()
    for path in content_files:
        for row in _iter_jsonl(path) or []:
            content_rows += 1
            count_value = _first(row, "comment_count", "comments_count", "comment_num", "video_comment", "total_comments")
            try:
                if int(float(str(count_value or "0").replace(",", ""))) > 0:
                    content_comment_count_positive += 1
            except Exception:
                pass
            region = _region(row)
            if region:
                content_regions[region] += 1

    comment_rows = 0
    first_level = 0
    nested = 0
    linked = 0
    comment_regions = Counter()
    comment_ids = set()
    nested_parent_ids = []
    for path in comment_files:
        for row in _iter_jsonl(path) or []:
            comment_rows += 1
            cid = str(_first(row, "comment_id", "cid", "rpid") or "").strip()
            parent = str(_first(
                row, "parent_comment_id", "parent_id", "reply_comment_id",
                "reply_to_comment_id", "reply_to_id", "parent_rpid"
            ) or "").strip()
            if cid:
                comment_ids.add(cid)
            if parent:
                nested += 1
                linked += 1
                nested_parent_ids.append(parent)
            else:
                first_level += 1
            region = _region(row)
            if region:
                comment_regions[region] += 1

    orphan_parents = sum(1 for pid in nested_parent_ids if pid and pid not in comment_ids)
    parent_integrity = round((linked - orphan_parents) / nested, 4) if nested else 1.0

    return {
        "available": True,
        "cycle": cycle.name,
        "content_rows": content_rows,
        "comment_rows": comment_rows,
        "first_level_comments": first_level,
        "nested_replies": nested,
        "parent_linked_replies": linked,
        "orphan_parent_links": orphan_parents,
        "parent_integrity_rate": parent_integrity,
        "comment_public_ip_region_records": sum(comment_regions.values()),
        "content_public_ip_region_records": sum(content_regions.values()),
        "comment_public_ip_region_rate": round(sum(comment_regions.values()) / comment_rows, 4) if comment_rows else 0.0,
        "content_public_ip_region_rate": round(sum(content_regions.values()) / content_rows, 4) if content_rows else 0.0,
        "comment_regions": dict(comment_regions.most_common()),
        "content_regions": dict(content_regions.most_common()),
        "content_comment_count_positive": content_comment_count_positive,
        "content_files": [str(p) for p in content_files],
        "comment_files": [str(p) for p in comment_files],
    }


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
    source_types = summary.get("source_types") or {}

    run = (status.get("platform_runs") or [{}])[0]
    ingest = (status.get("ingest") or [{}])[0]
    raw = _raw_acceptance(root)

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

    effective_content = max(unique_records - comment_records, int(raw.get("content_rows") or 0))
    effective_comments = max(comment_records, int(raw.get("comment_rows") or 0))

    checks = {
        "content_collected": effective_content > 0,
        "raw_comments_collected": effective_comments > 0,
        "source_type_classification_present": bool(source_types),
        "first_level_comments_present": root_comments > 0 or int(raw.get("first_level_comments") or 0) > 0,
        "nested_replies_present": replies > 0 or int(raw.get("nested_replies") or 0) > 0,
        "nested_parent_links_complete": (
            (replies == 0 or linked == replies)
            and float(raw.get("parent_integrity_rate") or 0.0) == 1.0
        ),
        "comment_public_ip_region_present": comment_region > 0 or int(raw.get("comment_public_ip_region_records") or 0) > 0,
        "content_public_ip_region_present": region_records > 0 or int(raw.get("content_public_ip_region_records") or 0) > 0,
        "comment_ingest_enabled": bool(cfg.get("ingest_comments", False) or ingest.get("ingest_comments", False)),
        "classification_degraded": bool(ingest.get("classification_degraded", False)),
    }

    result = {
        "ok": bool(checks["content_collected"] and checks["raw_comments_collected"] and checks["comment_ingest_enabled"]),
        "platform": "ks",
        "config": str(cfg_path),
        "data_root": str(root),
        "latest_cycle": {
            "finished_at": status.get("cycle_finished_at"),
            "crawler_state": run.get("state"),
            "duration_seconds": run.get("duration_seconds"),
            "realtime_target_seconds": status.get("realtime_target_seconds", 300),
            "realtime_cycle_within_target": status.get("realtime_cycle_within_target"),
            "content_rows": run.get("content_row_count", 0),
            "comment_rows": run.get("comment_row_count", 0),
            "detail_recovery_candidates": run.get("detail_recovery_candidates", 0),
            "detail_recovery_batches": run.get("detail_recovery_batches", 0),
            "deep_queue_pending": run.get("deep_queue_pending", 0),
        },
        "raw_ppt_fields": raw,
        "classified_ppt_fields": {
            "videos_or_posts": max(0, unique_records - comment_records),
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
            "raw_rows": ingest.get("raw_rows", 0),
            "raw_comment_rows": ingest.get("raw_comment_rows", 0),
            "normalized_records": ingest.get("normalized_records", 0),
            "normalized_comment_records": ingest.get("normalized_comment_records", 0),
            "classified_records": ingest.get("classified_records", 0),
            "classified_comment_records": ingest.get("classified_comment_records", 0),
            "classification_degraded_records": ingest.get("classification_degraded_records", 0),
            "classification_degraded_comment_records": ingest.get("classification_degraded_comment_records", 0),
            "classification_errors": ingest.get("classification_errors") or [],
            "duplicate_skipped": ingest.get("duplicate_skipped", 0),
            "filtered_before_start": ingest.get("filtered_before_start", 0),
        },
        "checks": checks,
        "interpretation": {
            "raw_vs_classified": (
                "raw_ppt_fields are read directly from the latest MediaCrawler JSONL and remain inspectable even if the attitude classifier is unavailable; "
                "classified_ppt_fields come from normalized/classified output."
            ),
            "source_type": (
                "source_type is the monitoring system's reporting classification (heuristic/LLM from public account name/content), "
                "not a claim that Kuaishou supplied an official verification badge unless such a public field is separately present in raw data."
            ),
            "ip": "Only platform-displayed coarse IP-location labels are retained; real IP addresses and precise locations are not collected.",
        },
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
