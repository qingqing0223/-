from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor.result_summary import build_summary

PLATFORMS = ("xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def platform_roots(cfg: dict, platform: str) -> list[Path]:
    base = Path(cfg["data_root"])
    candidates = [
        base.parent / f"{base.name}_{platform}",
        base.parent / f"{base.name}_multilingual_{platform}",
    ]
    return [p for p in candidates if p.exists()]


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify one student's final monitoring cycle end-to-end.")
    ap.add_argument("--platform", required=True, choices=PLATFORMS)
    ap.add_argument("--config", default=str(ROOT / "config" / "monitoring.local.json"))
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = load_json(cfg_path)
    roots = platform_roots(cfg, args.platform)
    summary = build_summary(roots, monitoring_start_time=str(cfg.get("monitoring_start_time") or ""))
    runtime = summary.get("runtime") or []
    latest_runtime = runtime[-1] if runtime else {}
    totals = summary.get("totals") or {}

    configured = {
        "search_until_exhausted": bool(cfg.get("search_until_exhausted")),
        "get_comment": str(cfg.get("get_comment", "")).lower() in {"yes", "true", "1", "y", "t"},
        "get_sub_comment": str(cfg.get("get_sub_comment", "")).lower() in {"yes", "true", "1", "y", "t"},
        "ingest_comments": bool(cfg.get("ingest_comments")),
        "comments_until_exhausted": bool(cfg.get("comments_until_exhausted")),
    }

    diagnostic = {
        "ok": bool(roots),
        "platform": args.platform,
        "config": str(cfg_path),
        "data_roots": [str(p) for p in roots],
        "configured": configured,
        "last_cycle": latest_runtime,
        "summary_schema_version": summary.get("schema_version"),
        "records": {
            "unique_records": totals.get("unique_records", 0),
            "record_types": summary.get("record_types") or {},
            "attitude": summary.get("attitude") or {},
            "regions": summary.get("regions") or {},
            "keywords": summary.get("keywords") or {},
        },
        "comments": {
            "comment_input_file_count": latest_runtime.get("comment_input_file_count", 0),
            "comment_records": totals.get("comment_records", 0),
            "root_comment_records": totals.get("root_comment_records", 0),
            "reply_comment_records": totals.get("reply_comment_records", 0),
            "parent_linked_comment_records": totals.get("parent_linked_comment_records", 0),
            "comment_regions": summary.get("comment_regions") or {},
            "comment_attitude": summary.get("comment_attitude") or {},
        },
        "public_accounts": {
            "count": totals.get("public_publisher_accounts", 0),
            "sample": (summary.get("public_account_stats") or [])[:10],
        },
        "video_analysis": summary.get("video_analysis") or {},
        "interpretation": {},
    }

    if latest_runtime:
        state = latest_runtime.get("crawler_state")
        diagnostic["interpretation"]["crawler"] = (
            "success" if state == "SUCCESS" else f"needs_attention:{state}"
        )
    else:
        diagnostic["interpretation"]["crawler"] = "no_completed_cycle_yet"

    comment_files = int(latest_runtime.get("comment_input_file_count") or 0)
    comment_records = int(totals.get("comment_records") or 0)
    if not all(configured[k] for k in ("get_comment", "get_sub_comment", "ingest_comments")):
        diagnostic["interpretation"]["comments"] = "comment_matrix_not_enabled"
    elif comment_files == 0:
        diagnostic["interpretation"]["comments"] = "enabled_but_upstream_generated_no_comment_jsonl_yet"
    elif comment_records == 0:
        diagnostic["interpretation"]["comments"] = "comment_jsonl_found_but_no_comment_record_reached_classified_output"
    else:
        diagnostic["interpretation"]["comments"] = "comments_classified_successfully"

    if int(totals.get("region_records") or 0) > 0:
        diagnostic["interpretation"]["region"] = "public_region_labels_collected"
    else:
        diagnostic["interpretation"]["region"] = "no_public_region_label_seen_yet"

    print(json.dumps(diagnostic, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
