from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Canonical path contract: results/<date>/platforms/<platform>.json
# Consumers should read these rollups instead of selecting a node shard directly.
PLATFORMS = (
    "xhs", "dy", "ks", "bili", "wb", "toutiao", "zhihu",
    "wechat_mp", "wechat_channels",
)


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def as_int(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def standard_node(payload: dict) -> bool:
    summary = payload.get("summary")
    return isinstance(summary, dict) and isinstance(summary.get("totals"), dict)


def node_snapshot(path: Path, payload: dict) -> dict:
    summary = payload.get("summary") or {}
    totals = summary.get("totals") or {}
    runtime = summary.get("runtime") or []
    last_runtime = runtime[-1] if runtime else {}
    return {
        "node_id": payload.get("node_id") or path.stem,
        "file": path.relative_to(ROOT).as_posix(),
        "schema_version": payload.get("schema_version"),
        "generated_at": payload.get("generated_at") or summary.get("generated_at") or "",
        "latest_seen_time": summary.get("latest_seen_time") or "",
        "unique_records": as_int(totals.get("unique_records")),
        "comment_records": as_int(totals.get("comment_records")),
        "root_comment_records": as_int(totals.get("root_comment_records")),
        "reply_comment_records": as_int(totals.get("reply_comment_records")),
        "region_records": as_int(totals.get("region_records")),
        "comment_region_records": as_int(totals.get("comment_region_records")),
        "crawler_state": last_runtime.get("crawler_state") or payload.get("acceptance", {}).get("crawler_state") or "",
        "fingerprint_records": len(payload.get("record_fingerprints") or []),
        "has_record_fingerprints": isinstance(payload.get("record_fingerprints"), list),
    }


def choose_authoritative(standard: list[tuple[Path, dict]]) -> tuple[Path, dict]:
    def key(item):
        path, payload = item
        summary = payload.get("summary") or {}
        totals = summary.get("totals") or {}
        return (
            as_int(totals.get("unique_records")),
            str(summary.get("latest_seen_time") or ""),
            str(payload.get("generated_at") or ""),
            path.name,
        )
    return max(standard, key=key)


def latest_node(standard: list[tuple[Path, dict]]) -> tuple[Path, dict]:
    return max(
        standard,
        key=lambda item: (
            str(item[1].get("generated_at") or ""),
            str((item[1].get("summary") or {}).get("latest_seen_time") or ""),
            item[0].name,
        ),
    )


def summary_from_fingerprints(records: list[dict], platform: str, generated_at: str) -> dict:
    record_type = Counter()
    attitude = Counter()
    status = Counter()
    type_counts = Counter()
    languages = Counter()
    regions = Counter()
    content_regions = Counter()
    comment_regions = Counter()
    source_types = Counter()
    keywords = Counter()
    comment_attitude = Counter()
    comment_status = Counter()
    comment_types = Counter()
    engagement = Counter()
    publishers = set()
    comment_authors = set()
    latest_seen = ""

    root_comments = 0
    reply_comments = 0
    parent_linked = 0
    comment_count = 0
    comment_region_count = 0
    video_records = 0
    with_asr = 0
    with_ocr = 0
    multimodal_complete = 0

    for r in records:
        rt = str(r.get("record_type") or "unknown")
        att = str(r.get("attitude") or "unknown")
        st = str(r.get("status") or "unknown")
        tp = str(r.get("type") or "null")
        lang = str(r.get("language") or "未知")
        reg = str(r.get("region") or "")
        source = str(r.get("source_type") or "未分类")
        keyword = str(r.get("keyword") or "")

        record_type[rt] += 1
        attitude[att] += 1
        status[st] += 1
        type_counts[tp] += 1
        languages[lang] += 1
        if reg:
            regions[reg] += 1
        source_types[source] += 1
        if keyword:
            keywords[keyword] += 1

        for k in ("likes", "comments", "shares", "views", "favorites", "danmaku", "coins"):
            engagement[k] += as_int(r.get(k))

        seen = str(r.get("latest_seen_time") or "")
        if seen > latest_seen:
            latest_seen = seen

        if rt == "comment":
            comment_count += 1
            comment_attitude[att] += 1
            comment_status[st] += 1
            comment_types[tp] += 1
            if reg:
                comment_region_count += 1
                comment_regions[reg] += 1
            level = as_int(r.get("comment_level"))
            parent_hash = str(r.get("parent_hash") or "")
            if level >= 2 or parent_hash:
                reply_comments += 1
            else:
                root_comments += 1
            if parent_hash:
                parent_linked += 1
            if r.get("author_hash"):
                comment_authors.add(str(r.get("author_hash")))
        else:
            if reg:
                content_regions[reg] += 1
            if r.get("publisher_hash"):
                publishers.add(str(r.get("publisher_hash")))

        if rt == "video":
            video_records += 1
            has_asr = bool(r.get("has_asr"))
            has_ocr = bool(r.get("has_ocr"))
            with_asr += int(has_asr)
            with_ocr += int(has_ocr)
            multimodal_complete += int(has_asr and has_ocr)

    total = len(records)
    region_total = sum(regions.values())
    return {
        "schema_version": 7,
        "generated_at": generated_at,
        "latest_seen_time": latest_seen,
        "privacy": "exact_cross_node_dedupe_from_privacy_safe_record_fingerprints",
        "totals": {
            "unique_records": total,
            "region_records": region_total,
            "region_coverage_rate": round(region_total / total, 4) if total else 0.0,
            "comment_records": comment_count,
            "root_comment_records": root_comments,
            "reply_comment_records": reply_comments,
            "parent_linked_comment_records": parent_linked,
            "comment_parent_link_rate": round(parent_linked / reply_comments, 4) if reply_comments else 0.0,
            "comment_region_records": comment_region_count,
            "comment_region_coverage_rate": round(comment_region_count / comment_count, 4) if comment_count else 0.0,
            "unique_comment_authors": len(comment_authors),
            "public_publisher_accounts": len(publishers),
            "likes": engagement["likes"],
            "comments": engagement["comments"],
            "shares": engagement["shares"],
            "views": engagement["views"],
            "favorites": engagement["favorites"],
            "danmaku": engagement["danmaku"],
            "coins": engagement["coins"],
        },
        "platforms": {platform: total},
        "platform_attitude": {platform: dict(attitude.most_common())},
        "languages": dict(languages.most_common()),
        "regions": dict(regions.most_common()),
        "content_regions": dict(content_regions.most_common()),
        "comment_regions": dict(comment_regions.most_common()),
        "v2_status": dict(status.most_common()),
        "v2_type": dict(type_counts.most_common()),
        "attitude": dict(attitude.most_common()),
        "comment_v2_status": dict(comment_status.most_common()),
        "comment_v2_type": dict(comment_types.most_common()),
        "comment_attitude": dict(comment_attitude.most_common()),
        "source_types": dict(source_types.most_common()),
        "record_types": dict(record_type.most_common()),
        "keywords": dict(keywords.most_common()),
        "video_analysis": {
            "video_records": video_records,
            "with_asr": with_asr,
            "with_ocr": with_ocr,
            "multimodal_complete": multimodal_complete,
            "multimodal_completion_rate": round(multimodal_complete / video_records, 4) if video_records else 0.0,
        },
    }


def rollup_platform(day_root: Path, platform: str) -> dict | None:
    node_dir = day_root / "nodes" / platform
    if not node_dir.exists():
        return None

    all_nodes: list[tuple[Path, dict]] = []
    for path in sorted(node_dir.glob("*.json")):
        payload = read_json(path)
        if payload:
            all_nodes.append((path, payload))
    if not all_nodes:
        return None

    standard = [(p, x) for p, x in all_nodes if standard_node(x)]
    diagnostics = [(p, x) for p, x in all_nodes if not standard_node(x)]
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    if not standard:
        return {
            "schema_version": 1,
            "platform": platform,
            "generated_at": generated_at,
            "aggregation_mode": "diagnostic_nodes_only",
            "node_count": 0,
            "diagnostic_node_count": len(diagnostics),
            "nodes": [],
            "diagnostic_nodes": [node_snapshot(p, x) for p, x in diagnostics],
            "summary": {},
        }

    authority_path, authority = choose_authoritative(standard)
    latest_path, latest = latest_node(standard)
    authority_summary = authority.get("summary") or {}

    fingerprint_nodes = [(p, x) for p, x in standard if isinstance(x.get("record_fingerprints"), list)]
    all_have_fingerprints = len(fingerprint_nodes) == len(standard)
    exact_records: dict[str, tuple[str, dict]] = {}
    for _, payload in fingerprint_nodes:
        node_time = str(payload.get("generated_at") or "")
        for rec in payload.get("record_fingerprints") or []:
            if not isinstance(rec, dict):
                continue
            key = str(rec.get("record_hash") or "")
            if not key:
                continue
            old = exact_records.get(key)
            if old is None or node_time >= old[0]:
                exact_records[key] = (node_time, rec)

    if all_have_fingerprints:
        mode = "exact_cross_node_dedupe"
        summary = summary_from_fingerprints(
            [v[1] for v in exact_records.values()],
            platform,
            generated_at,
        )
        summary["monitoring_start_time"] = str(authority.get("monitoring_start_time") or "")
    elif len(standard) == 1:
        mode = "single_node_passthrough"
        summary = authority_summary
    else:
        mode = "conservative_authoritative_snapshot_pending_fingerprints"
        summary = authority_summary

    node_rows = [node_snapshot(p, x) for p, x in standard]
    diagnostic_rows = [node_snapshot(p, x) for p, x in diagnostics]
    upper_bound = sum(n["unique_records"] for n in node_rows)
    lower_bound = max((n["unique_records"] for n in node_rows), default=0)

    return {
        "schema_version": 2,
        "platform": platform,
        "results_date": day_root.name,
        "generated_at": generated_at,
        "aggregation_mode": mode,
        "aggregation_note": (
            "Exact cross-node totals are used only when every count-bearing node publishes "
            "privacy-safe record fingerprints. Until then, the largest complete node snapshot "
            "is the conservative reporting total so overlapping nodes are never blindly summed."
        ),
        "authoritative_node_id": authority.get("node_id") or authority_path.stem,
        "latest_node_id": latest.get("node_id") or latest_path.stem,
        "node_count": len(standard),
        "diagnostic_node_count": len(diagnostics),
        "all_counting_nodes_have_fingerprints": all_have_fingerprints,
        "fingerprint_union_records": len(exact_records),
        "known_unique_lower_bound": lower_bound,
        "naive_sum_upper_bound": upper_bound,
        "nodes": node_rows,
        "diagnostic_nodes": diagnostic_rows,
        "summary": summary,
    }


def build_day(day_root: Path) -> list[Path]:
    nodes_root = day_root / "nodes"
    if not nodes_root.exists():
        return []
    out_root = day_root / "platforms"
    out_root.mkdir(parents=True, exist_ok=True)
    written = []
    overview = {
        "schema_version": 1,
        "results_date": day_root.name,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "platforms": {},
    }
    for platform in PLATFORMS:
        rollup = rollup_platform(day_root, platform)
        if rollup is None:
            continue
        path = out_root / f"{platform}.json"
        path.write_text(json.dumps(rollup, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(path)
        summary = rollup.get("summary") or {}
        totals = summary.get("totals") or {}
        overview["platforms"][platform] = {
            "aggregation_mode": rollup.get("aggregation_mode"),
            "authoritative_node_id": rollup.get("authoritative_node_id"),
            "latest_node_id": rollup.get("latest_node_id"),
            "unique_records": as_int(totals.get("unique_records")),
            "comment_records": as_int(totals.get("comment_records")),
            "root_comment_records": as_int(totals.get("root_comment_records")),
            "reply_comment_records": as_int(totals.get("reply_comment_records")),
            "region_records": as_int(totals.get("region_records")),
            "comment_region_records": as_int(totals.get("comment_region_records")),
            "latest_seen_time": summary.get("latest_seen_time") or "",
            "node_count": rollup.get("node_count", 0),
            "all_counting_nodes_have_fingerprints": rollup.get("all_counting_nodes_have_fingerprints", False),
        }
    overview_path = out_root / "overview.json"
    overview_path.write_text(json.dumps(overview, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    written.append(overview_path)
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description="Build canonical per-platform rollups from distributed node result shards.")
    ap.add_argument("--date", default="")
    ap.add_argument("--all-dates", action="store_true")
    args = ap.parse_args()

    roots = []
    if args.all_dates:
        roots = sorted(p for p in (ROOT / "results").iterdir() if p.is_dir() and (p / "nodes").exists())
    else:
        date_key = args.date or datetime.now().astimezone().date().isoformat()
        roots = [ROOT / "results" / date_key]

    written = []
    built_roots = []
    for root in roots:
        if root.exists():
            written.extend(build_day(root))
            built_roots.append(root)

    # Stable latest path for dashboards, GPT checks and "current latest" tables.
    # Choose the newest available day independently per platform so a platform
    # with no shard today (for example wechat_mp) does not disappear from latest.
    if built_roots:
        target = ROOT / "results" / "latest" / "platforms"
        target.mkdir(parents=True, exist_ok=True)
        for old_file in target.glob("*.json"):
            old_file.unlink()

        latest_overview = {
            "schema_version": 2,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "selection": "newest_available_rollup_per_platform",
            "platforms": {},
        }
        for platform in PLATFORMS:
            candidates = [
                root / "platforms" / f"{platform}.json"
                for root in built_roots
                if (root / "platforms" / f"{platform}.json").exists()
            ]
            if not candidates:
                continue
            src = max(candidates, key=lambda p: p.parents[1].name)
            dst = target / src.name
            shutil.copyfile(src, dst)
            written.append(dst)

            rollup = read_json(src)
            summary = rollup.get("summary") or {}
            totals = summary.get("totals") or {}
            latest_overview["platforms"][platform] = {
                "source_results_date": rollup.get("results_date") or src.parents[1].name,
                "aggregation_mode": rollup.get("aggregation_mode"),
                "authoritative_node_id": rollup.get("authoritative_node_id"),
                "latest_node_id": rollup.get("latest_node_id"),
                "unique_records": as_int(totals.get("unique_records")),
                "comment_records": as_int(totals.get("comment_records")),
                "root_comment_records": as_int(totals.get("root_comment_records")),
                "reply_comment_records": as_int(totals.get("reply_comment_records")),
                "region_records": as_int(totals.get("region_records")),
                "comment_region_records": as_int(totals.get("comment_region_records")),
                "latest_seen_time": summary.get("latest_seen_time") or "",
                "node_count": rollup.get("node_count", 0),
                "all_counting_nodes_have_fingerprints": rollup.get("all_counting_nodes_have_fingerprints", False),
            }

        overview_dst = target / "overview.json"
        overview_dst.write_text(json.dumps(latest_overview, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(overview_dst)

    print(json.dumps({"ok": True, "written": [p.relative_to(ROOT).as_posix() for p in written]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
