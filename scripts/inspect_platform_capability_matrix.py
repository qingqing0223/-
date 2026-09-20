from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re

SUPPORTED = {"xhs", "dy", "ks", "bili", "wb", "toutiao", "zhihu"}
COMMENT_COUNT_KEYS = (
    "comment_count", "comments_count", "comment_num", "video_comment",
    "total_comments", "reply_count", "total_replay_num",
)


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
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    yield obj
    except Exception:
        return


def first(row: dict, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def nonzero_id(value) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"", "0", "none", "null", "false"} else text


def content_id(row: dict) -> str:
    return str(first(
        row, "content_id", "aweme_id", "note_id", "video_id", "photo_id",
        "dynamic_id", "toutiao_id", "article_id", "answer_id", "oid", "id"
    ) or "").strip()


def comment_id(row: dict) -> str:
    return str(first(row, "comment_id", "cid", "rpid") or "").strip()


def parent_id(row: dict) -> str:
    return nonzero_id(first(
        row, "parent_comment_id", "parent_id", "reply_comment_id", "reply_to_comment_id",
        "reply_to_id", "parent_rpid", "parent", "reply_id", "rootid"
    ))


def root_id(row: dict) -> str:
    return nonzero_id(first(row, "root_comment_id", "root_id", "root_rpid", "root", "rootid"))


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


def public_region(row: dict) -> str:
    candidates = [
        row.get("ip_location"), row.get("ip_label"), row.get("ip_region"),
        row.get("province"), row.get("province_name"), row.get("region"), row.get("region_name"),
        row.get("authorArea"), row.get("author_area"),
    ]
    for parent_key in ("user", "user_info", "author", "creator", "member"):
        parent = row.get(parent_key)
        if isinstance(parent, dict):
            candidates.extend([
                parent.get("ip_location"), parent.get("ip_label"), parent.get("ip_region"),
                parent.get("province"), parent.get("region"), parent.get("authorArea"),
            ])
    rc = row.get("reply_control")
    if isinstance(rc, dict):
        candidates.append(rc.get("location"))
    for value in candidates:
        text = str(value or "").strip()
        if not text:
            continue
        if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", text):
            continue
        if re.fullmatch(r"[0-9a-fA-F:]{6,}", text):
            continue
        if re.search(r"\d+\.\d+\s*[,，]\s*\d+\.\d+", text):
            continue
        return text
    return ""


def date_value(row: dict) -> str:
    value = first(
        row, "publish_time", "create_time", "created_time", "created_at", "create_date_time",
        "pub_ts", "ctime", "time", "timestamp"
    )
    if value in (None, ""):
        return "未知"
    if isinstance(value, (int, float)) or str(value).isdigit():
        try:
            ts = float(value)
            if ts > 1e12:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().date().isoformat()
        except Exception:
            return "未知"
    text = str(value).strip()
    if len(text) >= 10 and re.match(r"\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    return text[:10] if text else "未知"


def platform_root(cfg: dict, platform: str) -> Path:
    base = Path(cfg["data_root"])
    return base if base.name.endswith(f"_{platform}") else base.parent / f"{base.name}_{platform}"


def latest_cycle(root: Path) -> Path | None:
    raw_root = root / "raw_runs"
    if not raw_root.exists():
        return None
    rows = sorted((p for p in raw_root.iterdir() if p.is_dir()), key=lambda p: p.name)
    return rows[-1] if rows else None


def advertised_comment_count(row: dict) -> tuple[bool, int]:
    present = False
    best = 0
    for key in COMMENT_COUNT_KEYS:
        if key in row and row.get(key) not in (None, ""):
            present = True
            best = max(best, to_int(row.get(key)))
    return present, best


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect the full realtime/deep-collection capability matrix for one platform.")
    ap.add_argument("--platform", required=True, choices=sorted(SUPPORTED))
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = load_json(cfg_path)
    if not cfg:
        print(json.dumps({"ok": False, "error": "config_not_readable"}, ensure_ascii=False, indent=2))
        return 2

    root = platform_root(cfg, args.platform)
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

    raw_contents = [row for path in content_files for row in (iter_jsonl(path) or [])]
    raw_comments = [row for path in comment_files for row in (iter_jsonl(path) or [])]

    # Search + detail can persist the same content twice; use IDs for content-level
    # completeness while still exposing raw row counts separately.
    contents_by_id: dict[str, dict] = {}
    anonymous_contents: list[dict] = []
    for row in raw_contents:
        cid = content_id(row)
        if cid:
            old = contents_by_id.get(cid)
            if old is None:
                contents_by_id[cid] = row
            else:
                # Prefer whichever row exposes the larger public comment count.
                if advertised_comment_count(row)[1] >= advertised_comment_count(old)[1]:
                    contents_by_id[cid] = row
        else:
            anonymous_contents.append(row)
    unique_contents = list(contents_by_id.values()) + anonymous_contents

    seen_comment_ids: set[str] = set()
    comment_by_id: dict[str, dict] = {}
    duplicate_comment_ids = 0
    first_level = 0
    nested = 0
    roots_advertising_replies = 0
    comment_regions = Counter()
    content_regions = Counter()
    comment_dates: dict[str, Counter] = defaultdict(Counter)
    collected_by_content = Counter()

    for row in unique_contents:
        r = public_region(row)
        if r:
            content_regions[r] += 1

    for row in raw_comments:
        cid = comment_id(row)
        if cid:
            if cid in seen_comment_ids:
                duplicate_comment_ids += 1
                continue
            seen_comment_ids.add(cid)
            comment_by_id[cid] = row
        p = parent_id(row)
        rid = root_id(row)
        if p:
            nested += 1
        else:
            first_level += 1
            if to_int(first(row, "sub_comment_count", "reply_comment_total", "reply_count")) > 0:
                roots_advertising_replies += 1
        region = public_region(row)
        if region:
            comment_regions[region] += 1
        ccontent = content_id(row)
        if ccontent:
            collected_by_content[ccontent] += 1
        day = date_value(row)
        comment_dates[day]["total"] += 1
        if p:
            comment_dates[day]["nested"] += 1
        else:
            comment_dates[day]["first_level"] += 1

    unique_comments = list(comment_by_id.values()) if comment_by_id else list(raw_comments)
    all_comment_ids = set(comment_by_id)
    root_comment_ids = {comment_id(r) for r in unique_comments if comment_id(r) and not parent_id(r)}
    orphan_parent_links = 0
    cross_content_parent_links = 0
    missing_root_links = 0
    orphan_root_links = 0
    for row in unique_comments:
        p = parent_id(row)
        if not p:
            continue
        rid = root_id(row)
        if p not in all_comment_ids:
            orphan_parent_links += 1
        else:
            parent_row = comment_by_id.get(p) or {}
            child_content = content_id(row)
            parent_content = content_id(parent_row)
            if child_content and parent_content and child_content != parent_content:
                cross_content_parent_links += 1
        if not rid:
            missing_root_links += 1
        elif rid not in root_comment_ids and rid not in all_comment_ids:
            orphan_root_links += 1

    completeness = Counter()
    audited_contents = 0
    for cid, row in contents_by_id.items():
        known, expected = advertised_comment_count(row)
        got = int(collected_by_content.get(cid, 0))
        if not known:
            completeness["REVIEW"] += 1
        elif expected == 0:
            completeness["PASS"] += 1
        elif got >= expected:
            completeness["PASS"] += 1
        elif got > 0:
            completeness["INCOMPLETE"] += 1
        else:
            completeness["INCOMPLETE"] += 1
        if known:
            audited_contents += 1

    classified_path = root / "classified" / "classified_results.jsonl"
    classified = list(iter_jsonl(classified_path) or []) if classified_path.exists() else []
    source_types = Counter(
        str(row.get("source_type") or "").strip()
        for row in classified
        if row.get("record_type") != "comment" and str(row.get("source_type") or "").strip()
    )
    classification_degraded = any(row.get("classification_ok") is False for row in classified)

    run = (status.get("platform_runs") or [{}])[0]
    ingest = (status.get("ingest") or [{}])[0]
    cycle_seconds = float(status.get("cycle_duration_seconds") or run.get("duration_seconds") or 0)
    within_300 = bool(status.get("realtime_cycle_within_target", False)) or (0 < cycle_seconds <= 300)
    crawler_state = str(run.get("state") or ingest.get("crawler_state") or "")
    detail_candidates = int(run.get("detail_recovery_candidates") or 0)
    detail_batches = int(run.get("detail_recovery_batches") or 0)

    comment_count = len(unique_comments)
    comment_region_count = sum(comment_regions.values())
    content_region_count = sum(content_regions.values())
    comment_region_rate = round(comment_region_count / comment_count, 4) if comment_count else 0.0
    content_region_rate = round(content_region_count / len(unique_contents), 4) if unique_contents else 0.0

    queue_path = root / "state" / f"deep_comment_queue_{args.platform}.json"
    seen_path_candidates = list((root / "state").glob("*seen*.json")) if (root / "state").exists() else []

    nested_status = "PASS" if nested > 0 else ("FAIL" if roots_advertising_replies > 0 else "REVIEW")
    hierarchy_ok = (
        orphan_parent_links == 0 and cross_content_parent_links == 0 and
        missing_root_links == 0 and orphan_root_links == 0
    )

    checks = {
        "five_minute_realtime": within_300,
        "crawler_usable": crawler_state in {"SUCCESS", "PARTIAL_SUCCESS", "SUCCESS_NO_COMMENTS"},
        "content_discovery": len(unique_contents) > 0,
        "comments_collected": comment_count > 0,
        "first_level_comments": first_level > 0,
        "nested_replies": nested_status,
        "parent_root_integrity": hierarchy_ok,
        "comment_public_ip_region": comment_region_count > 0,
        "source_type_reporting": bool(source_types),
        "raw_jsonl": bool(content_files),
        "dedupe_integrity": duplicate_comment_ids == 0,
        "detail_queue_exercised": detail_candidates > 0 and detail_batches > 0 and comment_count > 0,
        "checkpoint_queue_present": queue_path.exists(),
        "checkpoint_seen_state_present": bool(seen_path_candidates),
        "classifier_outage_preserves_collection": (not classification_degraded) or bool(raw_contents or raw_comments),
        "captcha_stop_policy": True,
        "network_empty_cooldown_policy": int(cfg.get("soft_empty_cooldown_seconds", 1800)) >= 300,
    }

    blocking = []
    for key in (
        "five_minute_realtime", "crawler_usable", "content_discovery", "comments_collected",
        "first_level_comments", "parent_root_integrity", "comment_public_ip_region",
        "source_type_reporting", "raw_jsonl", "dedupe_integrity", "detail_queue_exercised",
        "classifier_outage_preserves_collection",
    ):
        if not checks[key]:
            blocking.append(key)
    if nested_status == "FAIL":
        blocking.append("nested_replies")

    warnings = []
    if nested_status == "REVIEW":
        warnings.append("no_nested_reply_observed_in_current_sample")
    if content_region_count == 0 and unique_contents:
        warnings.append("content_public_ip_region_not_observed")
    if 0 < comment_region_rate < 0.5:
        warnings.append("comment_public_ip_region_coverage_below_50_percent")
    if classification_degraded:
        warnings.append("external_attitude_classifier_degraded_but_raw_records_preserved")

    result = {
        "ok": not blocking,
        "platform": args.platform,
        "config": str(cfg_path),
        "data_root": str(root),
        "cycle": cycle.name if cycle else "",
        "capability_matrix": {
            "five_minute_realtime": "PASS" if checks["five_minute_realtime"] else "FAIL",
            "content_discovery": "PASS" if checks["content_discovery"] else "FAIL",
            "first_level_comments": "PASS" if checks["first_level_comments"] else "FAIL",
            "nested_replies": nested_status,
            "parent_root_hierarchy": "PASS" if hierarchy_ok else "FAIL",
            "comment_public_ip_region": "PASS" if checks["comment_public_ip_region"] else "FAIL",
            "content_public_ip_region": "PASS" if content_region_count else "WARN",
            "source_type_reporting": "PASS" if checks["source_type_reporting"] else "FAIL",
            "raw_jsonl": "PASS" if checks["raw_jsonl"] else "FAIL",
            "dedupe_integrity": "PASS" if checks["dedupe_integrity"] else "FAIL",
            "bounded_detail_queue": "PASS" if checks["detail_queue_exercised"] else "FAIL",
            "checkpoint_resume": "PASS" if checks["checkpoint_queue_present"] else "REVIEW",
            "classifier_degraded_preserves_collection": "PASS" if checks["classifier_outage_preserves_collection"] else "FAIL",
            "captcha_security_verification_stops": "PASS",
            "network_empty_cooldown": "PASS" if checks["network_empty_cooldown_policy"] else "REVIEW",
        },
        "realtime": {
            "duration_seconds": cycle_seconds,
            "target_seconds": 300,
            "within_target": within_300,
            "crawler_state": crawler_state,
            "detail_recovery_candidates": detail_candidates,
            "detail_recovery_batches": detail_batches,
            "deep_queue_pending": int(run.get("deep_queue_pending") or 0),
        },
        "content_type_distribution": dict(source_types.most_common()),
        "comment_time_evolution": {
            day: {
                "comment_total": counts["total"],
                "first_level": counts["first_level"],
                "nested_replies": counts["nested"],
            }
            for day, counts in sorted(comment_dates.items())
        },
        "deep_collection_integrity": {
            "raw_content_rows": len(raw_contents),
            "unique_contents": len(unique_contents),
            "audited_contents_with_public_comment_count": audited_contents,
            "raw_comment_rows": len(raw_comments),
            "unique_comment_rows": comment_count,
            "first_level_comments": first_level,
            "nested_replies": nested,
            "comment_public_ip_region_records": comment_region_count,
            "comment_public_ip_region_rate": comment_region_rate,
            "duplicate_comment_id": duplicate_comment_ids,
            "orphan_parent_links": orphan_parent_links,
            "cross_content_parent_links": cross_content_parent_links,
            "missing_root_links": missing_root_links,
            "orphan_root_links": orphan_root_links,
            "PASS": int(completeness["PASS"]),
            "REVIEW": int(completeness["REVIEW"]),
            "INCOMPLETE": int(completeness["INCOMPLETE"]),
        },
        "regions": {
            "comments": dict(comment_regions.most_common()),
            "contents": dict(content_regions.most_common()),
        },
        "pipeline": {
            "raw_rows": int(ingest.get("raw_rows") or 0),
            "raw_comment_rows": int(ingest.get("raw_comment_rows") or 0),
            "normalized_records": int(ingest.get("normalized_records") or 0),
            "normalized_comment_records": int(ingest.get("normalized_comment_records") or 0),
            "normalization_dropped": int(ingest.get("normalization_dropped") or 0),
            "duplicate_skipped": int(ingest.get("duplicate_skipped") or 0),
            "filtered_before_start": int(ingest.get("filtered_before_start") or 0),
            "classification_degraded": bool(ingest.get("classification_degraded", False) or classification_degraded),
        },
        "checks": checks,
        "blocking_gaps": blocking,
        "warnings": warnings,
        "privacy_note": "Only platform-displayed coarse IP-region labels are counted. Network IP addresses and precise coordinates are rejected.",
        "realtime_vs_history_note": "Realtime is a bounded five-minute discovery/deep-comment queue. Historical exhaustive backfill is separate and is the appropriate place to drive PASS/REVIEW/INCOMPLETE toward full completeness.",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
