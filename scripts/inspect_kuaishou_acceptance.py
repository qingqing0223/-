from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
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
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", text) or re.fullmatch(r"[0-9a-fA-F:]{6,}", text):
        return ""
    if re.search(r"\d+\.\d+\s*[,，]\s*\d+\.\d+", text):
        return ""
    return text


def _flatten(obj, prefix: str = "", depth: int = 0, max_depth: int = 4):
    if depth > max_depth:
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, (dict, list)):
                yield from _flatten(value, path, depth + 1, max_depth)
            else:
                yield path, value
    elif isinstance(obj, list):
        for item in obj[:5]:
            yield from _flatten(item, prefix, depth + 1, max_depth)


def _safe_probe_value(value) -> str:
    if value in (None, ""):
        return ""
    text = str(value).strip().replace("\r", " ").replace("\n", " ")
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", text) or re.fullmatch(r"[0-9a-fA-F:]{6,}", text):
        return "[network-address-rejected]"
    if re.search(r"\d+\.\d+\s*[,，]\s*\d+\.\d+", text):
        return "[precise-location-rejected]"
    return text[:160]


def _path_norm(path: str) -> str:
    return re.sub(r"[^a-z0-9]", "", path.lower())


def _count_value(value) -> int:
    text = str(value or "").strip().replace(",", "").replace("，", "")
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


def _probe_rows(rows: list[dict]) -> dict:
    comment_count_paths = defaultdict(lambda: {"occurrences": 0, "positive": 0, "samples": []})
    region_paths = defaultdict(lambda: {"occurrences": 0, "samples": []})
    verify_paths = defaultdict(lambda: {"occurrences": 0, "samples": []})

    count_needles = ("commentcount", "commentscount", "commentnum", "videocomment", "totalcomments", "replycount")
    region_needles = ("iplocation", "ipregion", "iplabel", "regionname", "province", "location")
    verify_needles = ("verified", "verify", "official", "cert", "badge", "authority", "authentication", "accounttype")

    for row in rows:
        for path, value in _flatten(row):
            norm = _path_norm(path)
            safe = _safe_probe_value(value)
            if any(token in norm for token in count_needles):
                item = comment_count_paths[path]
                item["occurrences"] += 1
                if _count_value(value) > 0:
                    item["positive"] += 1
                if safe and safe not in item["samples"] and len(item["samples"]) < 5:
                    item["samples"].append(safe)
            if any(token in norm for token in region_needles):
                item = region_paths[path]
                item["occurrences"] += 1
                if safe and safe not in item["samples"] and len(item["samples"]) < 5:
                    item["samples"].append(safe)
            if any(token in norm for token in verify_needles):
                item = verify_paths[path]
                item["occurrences"] += 1
                if safe and safe not in item["samples"] and len(item["samples"]) < 5:
                    item["samples"].append(safe)

    def clean(mapping):
        return {k: v for k, v in sorted(mapping.items())}

    return {
        "comment_count_candidates": clean(comment_count_paths),
        "region_candidates": clean(region_paths),
        "platform_verification_candidates": clean(verify_paths),
        "positive_comment_count_records": sum(v["positive"] for v in comment_count_paths.values()),
    }


def _raw_acceptance(root: Path) -> dict:
    cycle = _latest_cycle(root)
    if cycle is None:
        return {"available": False, "cycle": ""}

    jsonl_files = sorted(cycle.rglob("*.jsonl"))
    content_files = [p for p in jsonl_files if "content" in p.name.lower()]
    comment_files = [p for p in jsonl_files if "comment" in p.name.lower()]

    content_rows_list = []
    comment_rows_list = []
    for path in content_files:
        content_rows_list.extend(list(_iter_jsonl(path) or []))
    for path in comment_files:
        comment_rows_list.extend(list(_iter_jsonl(path) or []))

    content_regions = Counter()
    for row in content_rows_list:
        region = _region(row)
        if region:
            content_regions[region] += 1

    first_level = 0
    nested = 0
    linked = 0
    comment_regions = Counter()
    comment_ids = set()
    nested_parent_ids = []
    for row in comment_rows_list:
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
    content_probe = _probe_rows(content_rows_list)
    comment_probe = _probe_rows(comment_rows_list)

    return {
        "available": True,
        "cycle": cycle.name,
        "content_rows": len(content_rows_list),
        "comment_rows": len(comment_rows_list),
        "first_level_comments": first_level,
        "nested_replies": nested,
        "parent_linked_replies": linked,
        "orphan_parent_links": orphan_parents,
        "parent_integrity_rate": parent_integrity,
        "comment_public_ip_region_records": sum(comment_regions.values()),
        "content_public_ip_region_records": sum(content_regions.values()),
        "comment_public_ip_region_rate": round(sum(comment_regions.values()) / len(comment_rows_list), 4) if comment_rows_list else 0.0,
        "content_public_ip_region_rate": round(sum(content_regions.values()) / len(content_rows_list), 4) if content_rows_list else 0.0,
        "comment_regions": dict(comment_regions.most_common()),
        "content_regions": dict(content_regions.most_common()),
        "content_comment_count_positive": int(content_probe.get("positive_comment_count_records") or 0),
        "content_schema_probe": content_probe,
        "comment_schema_probe": comment_probe,
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
    legacy_totals = summary.get("totals") or {}
    legacy_source_types = summary.get("source_types") or {}

    run = (status.get("platform_runs") or [{}])[0]
    ingest = (status.get("ingest") or [{}])[0]
    raw = _raw_acceptance(root)

    reprocess = _load(root / "acceptance" / "ks_reprocess_latest.json")
    if reprocess and str(reprocess.get("source_cycle") or "") != str(raw.get("cycle") or ""):
        reprocess = {}
    reprocess_ppt = reprocess.get("ppt_fields") or {}
    reprocess_pipeline = reprocess.get("pipeline") or {}
    reprocess_classification = reprocess.get("classification") or {}

    # If a current reprocess result exists, it is the authoritative post-normalization
    # acceptance view. The production classified file may legitimately still reflect
    # the earlier failed classifier run and must not overwrite a successful reprocess.
    effective_ppt = reprocess_ppt or {
        "videos_or_posts": max(0, int(legacy_totals.get("unique_records") or 0) - int(legacy_totals.get("comment_records") or 0)),
        "source_type_counts": legacy_source_types,
        "first_level_comments": int(legacy_totals.get("root_comment_records") or 0),
        "nested_replies": int(legacy_totals.get("reply_comment_records") or 0),
        "parent_linked_replies": int(legacy_totals.get("parent_linked_comment_records") or 0),
        "parent_integrity_rate": 1.0,
        "comment_public_ip_region_records": int(legacy_totals.get("comment_region_records") or 0),
        "content_public_ip_region_records": 0,
        "comment_regions": summary.get("comment_regions") or {},
        "content_regions": summary.get("content_regions") or {},
    }
    effective_pipeline = reprocess_pipeline or ingest

    effective_content = max(int(raw.get("content_rows") or 0), int(effective_ppt.get("videos_or_posts") or 0))
    effective_comments = max(int(raw.get("comment_rows") or 0), int(effective_pipeline.get("classified_comment_records") or 0))
    first_level = max(int(raw.get("first_level_comments") or 0), int(effective_ppt.get("first_level_comments") or 0))
    nested = max(int(raw.get("nested_replies") or 0), int(effective_ppt.get("nested_replies") or 0))
    parent_integrity = min(float(raw.get("parent_integrity_rate") or 1.0), float(effective_ppt.get("parent_integrity_rate") or 1.0))
    source_types = effective_ppt.get("source_type_counts") or {}
    queue_signal = int(raw.get("content_comment_count_positive") or 0) > 0

    checks = {
        "content_collected": effective_content > 0,
        "raw_comments_collected": effective_comments > 0,
        "source_type_classification_present": bool(source_types),
        "first_level_comments_present": first_level > 0,
        "nested_replies_present": nested > 0,
        "nested_parent_links_complete": parent_integrity == 1.0,
        "comment_public_ip_region_present": (
            int(raw.get("comment_public_ip_region_records") or 0) > 0
            or int(effective_ppt.get("comment_public_ip_region_records") or 0) > 0
        ),
        "content_public_ip_region_present": (
            int(raw.get("content_public_ip_region_records") or 0) > 0
            or int(effective_ppt.get("content_public_ip_region_records") or 0) > 0
        ),
        "comment_ingest_enabled": bool(cfg.get("ingest_comments", False) or ingest.get("ingest_comments", False)),
        "classification_degraded": bool(reprocess_classification.get("degraded", False) or effective_pipeline.get("classification_degraded", False)),
        "realtime_comment_queue_signal_present": queue_signal,
    }

    structural_ok = all([
        checks["content_collected"],
        checks["raw_comments_collected"],
        checks["source_type_classification_present"],
        checks["first_level_comments_present"],
        checks["nested_replies_present"],
        checks["nested_parent_links_complete"],
        checks["comment_ingest_enabled"],
    ])
    realtime_ready = structural_ok and checks["realtime_comment_queue_signal_present"]

    remaining_gaps = []
    if not checks["realtime_comment_queue_signal_present"]:
        remaining_gaps.append("content JSON has no positive comment-count signal; five-minute realtime detail queue cannot reliably select comment-bearing videos yet")
    if not checks["comment_public_ip_region_present"]:
        remaining_gaps.append("no platform-displayed coarse IP-region value found in current comment raw JSON")
    if not checks["content_public_ip_region_present"]:
        remaining_gaps.append("no platform-displayed coarse IP-region value found in current content raw JSON")
    if checks["classification_degraded"]:
        remaining_gaps.append("external attitude classifier is degraded; collected records are preserved as unclassified")

    result = {
        "ok": structural_ok,
        "realtime_ready": realtime_ready,
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
        "reprocessed_ppt_fields": effective_ppt,
        "pipeline": effective_pipeline,
        "classification": reprocess_classification,
        "checks": checks,
        "remaining_gaps": remaining_gaps,
        "interpretation": {
            "current_result_source": "acceptance/ks_reprocess_latest.json when its source_cycle matches the latest raw cycle; otherwise production classified summary",
            "source_type": (
                "source_type is the monitoring system's reporting classification from public account/content evidence. "
                "It is not the same as a Kuaishou platform verification badge. Check raw_ppt_fields.*_schema_probe.platform_verification_candidates for any public platform certification fields actually returned."
            ),
            "ip": (
                "Only platform-displayed coarse IP-location labels are retained. Network IP addresses and precise coordinates are rejected. "
                "If region counts are zero, inspect raw schema probe candidates before changing mappings."
            ),
            "realtime_queue": (
                "Five-minute realtime mode discovers content first and deep-crawls comments from a queue. "
                "A positive public comment-count field (or another safe queue signal) is required to enqueue comment-bearing videos without crawling all comments during discovery."
            ),
        },
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    # Structural acceptance may pass while realtime queue readiness is still pending.
    # Return non-zero until both are ready so local one-command recheck cannot falsely
    # announce that the five-minute Kuaishou path is fully complete.
    return 0 if realtime_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
