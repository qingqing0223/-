from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor.ingest import _canonical_public_region


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def iter_jsonl(path: Path):
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


def platform_root(cfg: dict) -> Path:
    base = Path(cfg["data_root"])
    return base if base.name.endswith("_dy") else base.parent / f"{base.name}_dy"


def latest_cycle(root: Path) -> Path | None:
    raw_root = root / "raw_runs"
    if not raw_root.exists():
        return None
    cycles = sorted((p for p in raw_root.iterdir() if p.is_dir()), key=lambda p: p.name)
    return cycles[-1] if cycles else None


def first(row: dict, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def nonzero_id(value) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"", "0", "none", "null", "false"} else text


def to_int(value) -> int:
    if value in (None, ""):
        return 0
    text = str(value).strip().replace(",", "").replace("，", "")
    try:
        if text.endswith("万"):
            return int(float(text[:-1]) * 10000)
        if text.lower().endswith("w"):
            return int(float(text[:-1]) * 10000)
        if text.lower().endswith("k"):
            return int(float(text[:-1]) * 1000)
        return int(float(text))
    except Exception:
        return 0


def region(row: dict) -> str:
    candidates = [
        row.get("ip_location"), row.get("ip_label"), row.get("ip_region"),
        row.get("province"), row.get("region"), row.get("region_name"),
    ]
    for parent_key in ("user", "user_info", "author", "creator"):
        parent = row.get(parent_key)
        if isinstance(parent, dict):
            candidates.extend([
                parent.get("ip_location"), parent.get("ip_label"), parent.get("ip_region"),
                parent.get("province"), parent.get("region"),
            ])
    for value in candidates:
        normalized = _canonical_public_region(value)
        if normalized:
            return normalized
    return ""


def flatten(obj, prefix="", depth=0, max_depth=4):
    if depth > max_depth:
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, (dict, list)):
                yield from flatten(value, path, depth + 1, max_depth)
            else:
                yield path, value
    elif isinstance(obj, list):
        for item in obj[:10]:
            yield from flatten(item, prefix, depth + 1, max_depth)


def schema_probe(rows: list[dict]) -> dict:
    region_fields = Counter()
    region_samples: dict[str, list[str]] = {}
    hierarchy_fields = Counter()
    for row in rows:
        for path, value in flatten(row):
            norm = re.sub(r"[^a-z0-9]", "", path.lower())
            if any(token in norm for token in ("iplabel", "iplocation", "ipregion", "province", "region")):
                region_fields[path] += 1
                sample = str(value or "").strip()
                if sample and not re.search(r"(?:\d{1,3}\.){3}\d{1,3}", sample):
                    values = region_samples.setdefault(path, [])
                    if sample not in values and len(values) < 5:
                        values.append(sample[:80])
            if any(token in norm for token in ("parentcommentid", "rootcommentid", "replyid", "subcommentcount")):
                hierarchy_fields[path] += 1
    return {
        "region_fields": dict(region_fields),
        "region_samples": region_samples,
        "hierarchy_fields": dict(hierarchy_fields),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Strict Douyin five-minute monitoring acceptance inspector.")
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = load_json(cfg_path)
    if not cfg:
        print(json.dumps({"ok": False, "error": "config_not_readable", "config": str(cfg_path)}, ensure_ascii=False, indent=2))
        return 2

    root = platform_root(cfg)
    status = load_json(root / "status" / "latest_status.json")
    cycle = latest_cycle(root)
    content_files: list[Path] = []
    comment_files: list[Path] = []
    if cycle:
        for path in sorted(cycle.rglob("*.jsonl")):
            low = path.name.lower()
            if "comment" in low:
                comment_files.append(path)
            elif "content" in low:
                content_files.append(path)

    contents = []
    comments = []
    for path in content_files:
        contents.extend(list(iter_jsonl(path) or []))
    for path in comment_files:
        comments.extend(list(iter_jsonl(path) or []))

    comment_ids = set()
    root_ids = set()
    reply_rows = []
    first_level = 0
    nested = 0
    roots_advertising_replies = 0
    duplicate_comment_ids = 0
    seen_comment_ids = set()
    comment_regions = Counter()
    content_regions = Counter()
    country_code_only_ip_location_rows = 0

    for row in contents:
        r = region(row)
        if r:
            content_regions[r] += 1

    for row in comments:
        raw_ip = str(row.get("ip_location") or "").strip()
        if re.fullmatch(r"[A-Za-z]{2,3}", raw_ip) or raw_ip in {"中国", "中国大陆", "中华人民共和国", "China", "Mainland China", "PRC"}:
            country_code_only_ip_location_rows += 1
        cid = str(first(row, "comment_id", "cid", "rpid") or "").strip()
        if cid:
            if cid in seen_comment_ids:
                duplicate_comment_ids += 1
            seen_comment_ids.add(cid)
            comment_ids.add(cid)
        parent = nonzero_id(first(
            row, "parent_comment_id", "parent_id", "reply_comment_id",
            "reply_to_comment_id", "reply_to_id", "parent_rpid"
        ))
        root_id = nonzero_id(first(row, "root_comment_id", "root_id", "root_rpid"))
        sub_count = to_int(first(row, "sub_comment_count", "reply_comment_total", "reply_count"))
        if parent:
            nested += 1
            reply_rows.append((cid, parent, root_id))
        else:
            first_level += 1
            if cid:
                root_ids.add(cid)
            if sub_count > 0:
                roots_advertising_replies += 1
        r = region(row)
        if r:
            comment_regions[r] += 1

    orphan_parent_links = sum(1 for _, parent, _ in reply_rows if parent and parent not in comment_ids)
    missing_root_links = sum(1 for _, _, root_id in reply_rows if not root_id)
    orphan_root_links = sum(1 for _, _, root_id in reply_rows if root_id and root_id not in root_ids)

    classified_path = root / "classified" / "classified_results.jsonl"
    classified_rows = list(iter_jsonl(classified_path) or []) if classified_path.exists() else []
    source_types = Counter(str(row.get("source_type") or "").strip() for row in classified_rows if str(row.get("source_type") or "").strip())
    classified_comment_rows = sum(1 for row in classified_rows if row.get("record_type") == "comment")
    classification_degraded = any(row.get("classification_ok") is False for row in classified_rows)

    run = (status.get("platform_runs") or [{}])[0]
    ingest = (status.get("ingest") or [{}])[0]
    cycle_seconds = float(status.get("cycle_duration_seconds") or run.get("duration_seconds") or 0)
    within_300 = bool(status.get("realtime_cycle_within_target", False)) or (cycle_seconds > 0 and cycle_seconds <= 300)
    crawler_state = str(run.get("state") or ingest.get("crawler_state") or "")
    detail_candidates = int(run.get("detail_recovery_candidates") or 0)
    detail_batches = int(run.get("detail_recovery_batches") or 0)

    comment_region_rate = round(sum(comment_regions.values()) / len(comments), 4) if comments else 0.0
    content_region_rate = round(sum(content_regions.values()) / len(contents), 4) if contents else 0.0

    checks = {
        "realtime_cycle_within_300s": within_300,
        "crawler_usable": crawler_state in {"SUCCESS", "PARTIAL_SUCCESS"},
        "content_collected": len(contents) > 0,
        "raw_jsonl_present": bool(content_files),
        "comments_collected": len(comments) > 0,
        "first_level_comments_present": first_level > 0,
        "nested_replies_present": nested > 0,
        "parent_links_complete": nested > 0 and orphan_parent_links == 0,
        "root_links_complete": nested > 0 and missing_root_links == 0 and orphan_root_links == 0,
        "duplicate_comment_ids_zero": duplicate_comment_ids == 0,
        "comment_public_ip_region_present": sum(comment_regions.values()) > 0,
        "content_public_ip_region_present": sum(content_regions.values()) > 0,
        "source_type_classification_present": bool(source_types),
        "comment_ingest_enabled": bool(cfg.get("ingest_comments", False) or ingest.get("ingest_comments", False)),
        "detail_queue_exercised": detail_candidates > 0 and detail_batches > 0 and len(comments) > 0,
        "classifier_outage_does_not_drop_raw": (not classification_degraded) or (len(contents) + len(comments) > 0),
    }

    blocking_keys = [
        "realtime_cycle_within_300s", "crawler_usable", "content_collected", "raw_jsonl_present",
        "comments_collected", "first_level_comments_present", "nested_replies_present",
        "parent_links_complete", "root_links_complete", "duplicate_comment_ids_zero",
        "comment_public_ip_region_present", "source_type_classification_present",
        "comment_ingest_enabled", "detail_queue_exercised", "classifier_outage_does_not_drop_raw",
    ]
    blocking_gaps = [key for key in blocking_keys if not checks[key]]
    warnings = []
    if not checks["content_public_ip_region_present"]:
        warnings.append("content_public_ip_region_not_observed")
    if country_code_only_ip_location_rows:
        warnings.append("douyin_country_code_only_ip_label_not_counted_as_region")
    if 0 < comment_region_rate < 0.5:
        warnings.append("comment_ip_region_coverage_below_50_percent")
    if roots_advertising_replies > 0 and nested == 0:
        warnings.append("roots_advertise_replies_but_no_nested_rows")
    if classification_degraded:
        warnings.append("external_attitude_classifier_degraded_but_raw_records_preserved")

    matrix = {
        "five_minute_realtime": "PASS" if checks["realtime_cycle_within_300s"] else "FAIL",
        "content_discovery": "PASS" if checks["content_collected"] else "FAIL",
        "first_level_comments": "PASS" if checks["first_level_comments_present"] else "FAIL",
        "nested_replies": "PASS" if checks["nested_replies_present"] else "FAIL",
        "parent_root_hierarchy": "PASS" if checks["parent_links_complete"] and checks["root_links_complete"] else "FAIL",
        "comment_public_ip_region": "PASS" if checks["comment_public_ip_region_present"] else "FAIL",
        "content_public_ip_region": "PASS" if checks["content_public_ip_region_present"] else "WARN",
        "source_type_reporting": "PASS" if checks["source_type_classification_present"] else "FAIL",
        "raw_jsonl": "PASS" if checks["raw_jsonl_present"] else "FAIL",
        "dedupe_integrity": "PASS" if checks["duplicate_comment_ids_zero"] else "FAIL",
        "bounded_detail_queue": "PASS" if checks["detail_queue_exercised"] else "FAIL",
        "classifier_degraded_preserves_collection": "PASS" if checks["classifier_outage_does_not_drop_raw"] else "FAIL",
    }

    result = {
        "ok": not blocking_gaps,
        "platform": "dy",
        "config": str(cfg_path),
        "data_root": str(root),
        "cycle": cycle.name if cycle else "",
        "latest_cycle": {
            "crawler_state": crawler_state,
            "duration_seconds": cycle_seconds,
            "realtime_target_seconds": 300,
            "realtime_cycle_within_target": within_300,
            "content_rows": len(contents),
            "comment_rows": len(comments),
            "detail_recovery_candidates": detail_candidates,
            "detail_recovery_batches": detail_batches,
            "deep_queue_pending": int(run.get("deep_queue_pending") or 0),
        },
        "function_matrix": matrix,
        "comments": {
            "comment_rows": len(comments),
            "first_level_comments": first_level,
            "nested_replies": nested,
            "roots_advertising_replies": roots_advertising_replies,
            "orphan_parent_links": orphan_parent_links,
            "missing_root_links": missing_root_links,
            "orphan_root_links": orphan_root_links,
            "duplicate_comment_ids": duplicate_comment_ids,
            "comment_public_ip_region_records": sum(comment_regions.values()),
            "comment_public_ip_region_rate": comment_region_rate,
            "comment_regions": dict(comment_regions.most_common()),
            "country_code_only_ip_location_rows": country_code_only_ip_location_rows,
        },
        "contents": {
            "content_rows": len(contents),
            "content_public_ip_region_records": sum(content_regions.values()),
            "content_public_ip_region_rate": content_region_rate,
            "content_regions": dict(content_regions.most_common()),
        },
        "reporting_source_types": dict(source_types.most_common()),
        "pipeline": {
            "raw_rows": int(ingest.get("raw_rows") or 0),
            "raw_comment_rows": int(ingest.get("raw_comment_rows") or 0),
            "normalized_records": int(ingest.get("normalized_records") or 0),
            "normalized_comment_records": int(ingest.get("normalized_comment_records") or 0),
            "classified_records": int(ingest.get("classified_records") or 0),
            "classified_comment_records": int(ingest.get("classified_comment_records") or classified_comment_rows),
            "duplicate_skipped": int(ingest.get("duplicate_skipped") or 0),
            "filtered_before_start": int(ingest.get("filtered_before_start") or 0),
            "classification_degraded": bool(ingest.get("classification_degraded", False) or classification_degraded),
        },
        "checks": checks,
        "blocking_gaps": blocking_gaps,
        "warnings": warnings,
        "comment_schema_probe": schema_probe(comments),
        "content_schema_probe": schema_probe(contents),
        "privacy_note": "Only platform-displayed coarse IP-region labels are accepted; network IP addresses and precise coordinates are rejected.",
        "source_type_note": "Source type is the monitoring system reporting classification, not a claim of Douyin platform verification unless a separate public verification field is present.",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
