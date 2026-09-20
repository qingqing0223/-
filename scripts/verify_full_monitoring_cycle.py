from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor.result_summary import build_summary
from pipeline.normalizer import normalize_record
from monitor.ingest import _before_monitoring_start

PLATFORMS = ("xhs", "dy", "ks", "bili", "wb", "toutiao", "zhihu")


def load_json(path: Path, default=None):
    if default is None:
        default = {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def iter_jsonl(path: Path):
    if not path.exists():
        return
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


def platform_roots(cfg: dict, platform: str) -> list[Path]:
    base = Path(cfg["data_root"])
    candidates = [
        base.parent / f"{base.name}_{platform}",
        base.parent / f"{base.name}_multilingual_{platform}",
    ]
    return [p for p in candidates if p.exists()]


def latest_status(roots: list[Path]) -> tuple[dict, dict, dict]:
    candidates = []
    for root in roots:
        path = root / "status" / "latest_status.json"
        if not path.exists():
            continue
        obj = load_json(path, {})
        candidates.append((str(obj.get("cycle_finished_at") or ""), obj))
    if not candidates:
        return {}, {}, {}
    _, status = max(candidates, key=lambda item: item[0])
    run = (status.get("platform_runs") or [{}])[0]
    ingest = (status.get("ingest") or [{}])[0]
    return status, run, ingest


def latest_raw_comment_scope(input_files: list[str], platform: str, monitoring_start_time: str) -> dict:
    normalized = 0
    before_start = 0
    after_or_unknown = 0
    for raw_path in input_files:
        path = Path(raw_path)
        if "comment" not in path.name.lower() or not path.exists():
            continue
        for raw in iter_jsonl(path) or []:
            rec = normalize_record(raw, source_file=path.name, platform_hint=platform)
            if not rec or rec.get("record_type") != "comment":
                continue
            normalized += 1
            if _before_monitoring_start(rec, monitoring_start_time):
                before_start += 1
            else:
                after_or_unknown += 1
    return {
        "normalized_comment_records": normalized,
        "before_monitoring_start": before_start,
        "after_or_unknown_time": after_or_unknown,
    }


def comment_integrity(roots: list[Path]) -> dict:
    rows = []
    for root in roots:
        rows.extend(list(iter_jsonl(root / "classified" / "classified_results.jsonl") or []))

    comments = [r for r in rows if str(r.get("record_type") or "") == "comment"]
    by_platform_comment_id: dict[tuple[str, str], dict] = {}
    for row in comments:
        cid = str(row.get("comment_id") or "").strip()
        platform = str(row.get("platform") or "").strip()
        if cid:
            by_platform_comment_id[(platform, cid)] = row

    replies = 0
    linked = 0
    orphan = 0
    cross_content = 0
    missing_comment_id = 0
    root_missing = 0

    for row in comments:
        cid = str(row.get("comment_id") or "").strip()
        platform = str(row.get("platform") or "").strip()
        content_id = str(row.get("content_id") or "").strip()
        parent_id = str(row.get("parent_comment_id") or "").strip()
        root_id = str(row.get("root_comment_id") or "").strip()
        level = int(row.get("comment_level") or 0)
        if not cid:
            missing_comment_id += 1
        if level >= 2 or parent_id:
            replies += 1
            if not parent_id:
                orphan += 1
            else:
                parent = by_platform_comment_id.get((platform, parent_id))
                if parent is None:
                    orphan += 1
                else:
                    linked += 1
                    parent_content = str(parent.get("content_id") or "").strip()
                    if content_id and parent_content and content_id != parent_content:
                        cross_content += 1
            if root_id and (platform, root_id) not in by_platform_comment_id:
                root_missing += 1

    return {
        "comment_records_scanned": len(comments),
        "reply_records_scanned": replies,
        "parent_linked_records": linked,
        "orphan_reply_records": orphan,
        "cross_content_parent_records": cross_content,
        "missing_comment_id_records": missing_comment_id,
        "missing_root_records": root_missing,
        "parent_integrity_rate": round(linked / replies, 4) if replies else 1.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify one student's monitoring cycle end-to-end and fail on broken critical chains.")
    ap.add_argument("--platform", required=True, choices=PLATFORMS)
    ap.add_argument("--config", default=str(ROOT / "config" / "monitoring.local.json"))
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = load_json(cfg_path, {})
    roots = platform_roots(cfg, args.platform) if cfg else []
    summary = build_summary(roots, monitoring_start_time=str(cfg.get("monitoring_start_time") or "")) if roots else {}
    totals = summary.get("totals") or {}
    status, run, ingest = latest_status(roots)

    configured = {
        "search_until_exhausted": bool(cfg.get("search_until_exhausted")),
        "get_comment": str(cfg.get("get_comment", "")).lower() in {"yes", "true", "1", "y", "t"},
        "get_sub_comment": str(cfg.get("get_sub_comment", "")).lower() in {"yes", "true", "1", "y", "t"},
        "ingest_comments": bool(cfg.get("ingest_comments")),
        "comments_until_exhausted": bool(cfg.get("comments_until_exhausted")),
    }

    input_files = [str(p) for p in (ingest.get("input_files") or [])]
    comment_files = [p for p in input_files if "comment" in Path(p).name.lower()]
    raw_comment_scope = latest_raw_comment_scope(
        input_files,
        args.platform,
        str(cfg.get("monitoring_start_time") or ""),
    )
    raw_content_rows = int(run.get("content_row_count") or ingest.get("raw_content_rows") or 0)
    raw_comment_rows = int(run.get("comment_row_count") or ingest.get("raw_comment_rows") or 0)
    normalized_comment_records = int(ingest.get("normalized_comment_records") or 0)
    classified_comment_records = int(ingest.get("classified_comment_records") or 0)
    filtered_comment_records = int(ingest.get("filtered_before_start_comment_records") or 0)
    filtered_comment_records_reported = "filtered_before_start_comment_records" in ingest
    duplicate_comment_records = int(ingest.get("duplicate_comment_skipped") or 0)
    duplicate_comment_records_reported = "duplicate_comment_skipped" in ingest
    integrity = comment_integrity(roots)

    failures = []
    warnings = []
    state = str(run.get("state") or "")

    if not roots:
        failures.append("no_platform_data_root")
    if not status:
        failures.append("no_completed_cycle_status")
    if not all(configured[k] for k in ("get_comment", "get_sub_comment", "ingest_comments")):
        failures.append("comment_matrix_not_enabled")
    if state in {"SOFT_EMPTY", "VERIFY_REQUIRED", "LOGIN_REQUIRED", "NETWORK_ERROR", "CRAWLER_FAILED", "RUNNER_ERROR"}:
        failures.append(f"crawler_state:{state}")
    if raw_comment_rows > 0 and normalized_comment_records == 0:
        failures.append("raw_comments_lost_during_normalization")
    if normalized_comment_records > 0 and classified_comment_records == 0 and int(ingest.get("duplicate_skipped") or 0) == 0:
        failures.append("normalized_comments_did_not_reach_classifier_output")
    if integrity["orphan_reply_records"] > 0:
        failures.append("orphan_reply_parent_links_detected")
    if integrity["cross_content_parent_records"] > 0:
        failures.append("cross_content_parent_links_detected")
    if integrity["missing_comment_id_records"] > 0:
        failures.append("comment_rows_missing_comment_id")

    visible_comment_count = int(totals.get("comments") or 0)
    cumulative_comment_records = int(totals.get("comment_records") or 0)
    if configured["get_comment"] and raw_content_rows > 0 and not comment_files:
        if visible_comment_count > 0:
            failures.append("content_reports_comments_but_no_comment_jsonl_generated")
        else:
            warnings.append("content_collected_but_no_comment_jsonl_generated")
    if comment_files and raw_comment_rows == 0:
        warnings.append("comment_jsonl_exists_but_contains_no_rows")
    # Raw comments can be validly absent from the production classified output when
    # every normalized comment is either outside monitoring_start_time or already
    # seen. Treat those as scope/dedupe accounting, not as a broken comment chain.
    accounted_comment_records = (
        classified_comment_records
        + filtered_comment_records
        + duplicate_comment_records
    )
    if raw_comment_rows > 0 and cumulative_comment_records == 0 and classified_comment_records == 0:
        snapshot_accounts_for_comments = (
            (filtered_comment_records_reported or duplicate_comment_records_reported)
            and accounted_comment_records >= normalized_comment_records
        )
        live_probe_accounts_for_comments = (
            int(raw_comment_scope.get("normalized_comment_records") or 0) >= normalized_comment_records
            and int(raw_comment_scope.get("before_monitoring_start") or 0) >= normalized_comment_records
        )
        if snapshot_accounts_for_comments or live_probe_accounts_for_comments:
            warnings.append("raw_comments_collected_but_all_excluded_by_scope_or_dedupe")
        else:
            failures.append("comment_rows_exist_but_no_comment_record_in_classified_output")
    if cumulative_comment_records > 0 and int(totals.get("comment_region_records") or 0) == 0:
        warnings.append("comments_collected_but_no_public_region_label_seen")

    diagnostic = {
        "ok": not failures,
        "platform": args.platform,
        "config": str(cfg_path),
        "data_roots": [str(p) for p in roots],
        "configured": configured,
        "last_cycle": run,
        "summary_schema_version": summary.get("schema_version"),
        "pipeline": {
            "content_input_file_count": int(run.get("content_file_count") or 0),
            "comment_input_file_count": len(comment_files) or int(run.get("comment_file_count") or 0),
            "raw_content_rows": raw_content_rows,
            "raw_comment_rows": raw_comment_rows,
            "normalized_comment_records": normalized_comment_records,
            "duplicate_skipped": int(ingest.get("duplicate_skipped") or 0),
            "filtered_before_start": int(ingest.get("filtered_before_start") or 0),
            "filtered_before_start_comment_records": filtered_comment_records if filtered_comment_records_reported else None,
            "filtered_before_start_content_records": int(ingest.get("filtered_before_start_content_records") or 0) if "filtered_before_start_content_records" in ingest else None,
            "duplicate_comment_skipped": duplicate_comment_records if duplicate_comment_records_reported else None,
            "duplicate_content_skipped": int(ingest.get("duplicate_content_skipped") or 0) if "duplicate_content_skipped" in ingest else None,
            "classified_records": int(ingest.get("classified_records") or 0),
            "classified_comment_records": classified_comment_records,
            "normalization_dropped": int(ingest.get("normalization_dropped") or 0),
        },
        "records": {
            "unique_records": totals.get("unique_records", 0),
            "record_types": summary.get("record_types") or {},
            "attitude": summary.get("attitude") or {},
            "regions": summary.get("regions") or {},
            "keywords": summary.get("keywords") or {},
        },
        "comments": {
            "comment_records": cumulative_comment_records,
            "latest_cycle_scope": {
                "raw_comment_rows": raw_comment_rows,
                "normalized_comment_records": normalized_comment_records,
                "classified_comment_records": classified_comment_records,
                "filtered_before_monitoring_start": filtered_comment_records if filtered_comment_records_reported else None,
                "duplicate_comment_records": duplicate_comment_records if duplicate_comment_records_reported else None,
                "raw_time_scope_probe": raw_comment_scope,
                "scope_note": (
                    "Pipeline counters come from the completed latest_status snapshot. "
                    "raw_time_scope_probe re-reads the current raw JSONL and is diagnostic only; "
                    "the counts can differ if a partial raw file changed after the status snapshot."
                ),
            },
            "root_comment_records": totals.get("root_comment_records", 0),
            "reply_comment_records": totals.get("reply_comment_records", 0),
            "parent_linked_comment_records": totals.get("parent_linked_comment_records", 0),
            "comment_regions": summary.get("comment_regions") or {},
            "comment_attitude": summary.get("comment_attitude") or {},
            "integrity": integrity,
        },
        "public_accounts": {
            "count": totals.get("public_publisher_accounts", 0),
            "sample": (summary.get("public_account_stats") or [])[:10],
        },
        "video_analysis": summary.get("video_analysis") or {},
        "failures": failures,
        "warnings": warnings,
    }

    print(json.dumps(diagnostic, ensure_ascii=False, indent=2))
    return 0 if diagnostic["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
