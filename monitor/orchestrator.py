from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import json
import time

from .crawler_runner import run_platform, find_ingest_jsonl
from .ingest import ingest_and_classify
from .keyword_pack import apply_keyword_pack
from pipeline.io_utils import write_json
from dashboard_adapter.suqi_pusher import deliver_with_outbox
from .zhihu_submission import export_zhihu_submission

ROOT = Path(__file__).resolve().parents[1]


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    return apply_keyword_pack(cfg, path)


def run_one_cycle(cfg: dict) -> dict:
    cycle_started_dt = datetime.now().astimezone()
    cycle_started_monotonic = time.time()
    data_root = Path(cfg["data_root"])
    stamp = cycle_started_dt.strftime("%Y%m%d_%H%M%S")
    cycle_root = data_root / "raw_runs" / stamp
    cycle_root.mkdir(parents=True, exist_ok=True)

    state_path = data_root / "state" / "seen_ids.json"
    classified_path = data_root / "classified" / "classified_results.jsonl"
    status_path = data_root / "status" / "latest_status.json"
    dashboard_outbox_path = data_root / "outbox" / "suqi_pending.jsonl"

    enabled = [p for p in cfg["platforms"] if p.get("enabled", True)]
    workers = max(1, int(cfg.get("max_parallel_platforms", 1)))
    monitoring_start_time = str(cfg.get("monitoring_start_time") or "")
    collection_only = bool(cfg.get("collection_only", False))

    runs = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_platform, cfg, p, cycle_root) for p in enabled]
        for future in as_completed(futures):
            runs.append(future.result())

    ingests = []
    new_classified_rows = []
    include_comments = bool(cfg.get("ingest_comments", False))
    for run in runs:
        files = find_ingest_jsonl(Path(run.output_dir), include_comments=include_comments)

        # The collection group owns only tables 1-5 for Zhihu.  Export those
        # rows before any analysis-stage classifier is considered.
        if run.platform == "zhihu" and files:
            export = export_zhihu_submission(
                files, cfg, ROOT, str(cfg.get("submission_node_id") or "zhihu01")
            )
        else:
            export = None

        if export is not None:
            ingests.append({
                "platform": "zhihu",
                "monitoring_start_time": monitoring_start_time,
                "new_records": export["accepted_rows"],
                "classified_records": 0,
                "classification": "not_run_collection_group_scope_only",
                "ingest_comments": include_comments,
                "input_files": [str(p) for p in files],
                "raw_content_rows": run.content_row_count,
                "raw_comment_rows": run.comment_row_count,
                "partial_crawler_result": run.status != "ok",
                "crawler_state": run.state,
                "table_1_to_5_export": export,
                "warning": "valid partial JSONL preserved" if run.status != "ok" else "",
            })
            continue

        if run.status != "ok" and not files:
            ingests.append({
                "platform": run.platform,
                "monitoring_start_time": monitoring_start_time,
                "new_records": 0,
                "filtered_before_start": 0,
                "classified_records": 0,
                "region_records": 0,
                "region_rate": 0.0,
                "minority_language_records": 0,
                "minority_language_rate": 0.0,
                "language_counts": {},
                "ingest_comments": include_comments,
                "input_files": [],
                "raw_content_rows": run.content_row_count,
                "raw_comment_rows": run.comment_row_count,
                "partial_crawler_result": False,
                "crawler_state": run.state,
                "skipped_reason": f"crawler_{run.status}_no_jsonl"
            })
            continue

        if not files:
            ingests.append({
                "platform": run.platform,
                "monitoring_start_time": monitoring_start_time,
                "new_records": 0,
                "filtered_before_start": 0,
                "classified_records": 0,
                "region_records": 0,
                "region_rate": 0.0,
                "minority_language_records": 0,
                "minority_language_rate": 0.0,
                "language_counts": {},
                "ingest_comments": include_comments,
                "input_files": [],
                "raw_content_rows": run.content_row_count,
                "raw_comment_rows": run.comment_row_count,
                "partial_crawler_result": False,
                "crawler_state": run.state,
                "skipped_reason": "soft_empty_no_jsonl" if run.state == "SOFT_EMPTY" else "no_ingest_jsonl"
            })
            continue

        try:
            summary = ingest_and_classify(
                run.platform,
                files,
                state_path,
                classified_path,
                int(cfg.get("classifier_concurrency", 4)),
                monitoring_start_time=monitoring_start_time,
                classify=not collection_only,
            )
            new_classified_rows.extend(summary.pop("_classified_rows", []))
            summary["ingest_comments"] = include_comments
            summary["raw_content_rows"] = run.content_row_count
            summary["raw_comment_rows"] = run.comment_row_count
            summary["partial_crawler_result"] = run.status != "ok"
            summary["crawler_state"] = run.state
            if export:
                summary["table_1_to_5_export"] = export
            if run.status != "ok":
                summary["warning"] = (
                    "crawler did not finish cleanly; valid JSONL already written "
                    "was preserved and ingested"
                )
            ingests.append(summary)
        except Exception as exc:
            ingests.append({
                "platform": run.platform,
                "monitoring_start_time": monitoring_start_time,
                "new_records": 0,
                "filtered_before_start": 0,
                "classified_records": 0,
                "region_records": 0,
                "region_rate": 0.0,
                "minority_language_records": 0,
                "minority_language_rate": 0.0,
                "language_counts": {},
                "ingest_comments": include_comments,
                "input_files": [str(p) for p in files],
                "raw_content_rows": run.content_row_count,
                "raw_comment_rows": run.comment_row_count,
                "partial_crawler_result": run.status != "ok",
                "crawler_state": run.state,
                "skipped_reason": f"classifier_error:{type(exc).__name__}:{exc}"
            })

    dashboard_cfg = cfg.get("dashboard", {}) or {}
    dashboard_push = {
        "enabled": bool(dashboard_cfg.get("enabled", False)),
        "sent": 0,
        "ok": None,
    }
    if dashboard_push["enabled"]:
        dashboard_push = deliver_with_outbox(
            new_classified_rows,
            ingest_url=str(dashboard_cfg.get("ingest_url", "")),
            outbox_path=dashboard_outbox_path,
            timeout_seconds=int(dashboard_cfg.get("timeout_seconds", 15)),
        )
        dashboard_push["enabled"] = True

    cycle_finished_dt = datetime.now().astimezone()
    cycle_duration = round(time.time() - cycle_started_monotonic, 2)
    realtime_target = max(60, int(cfg.get("interval_seconds", 300)))
    result = {
        "event_id": cfg.get("event_id"),
        "event_name": cfg.get("event_name"),
        "monitoring_start_time": monitoring_start_time,
        "results_date": cfg.get("results_date"),
        "cycle_started_at": cycle_started_dt.isoformat(timespec="seconds"),
        "cycle_finished_at": cycle_finished_dt.isoformat(timespec="seconds"),
        "cycle_duration_seconds": cycle_duration,
        "realtime_target_seconds": realtime_target,
        "realtime_cycle_within_target": cycle_duration <= realtime_target,
        "keyword_count": len(cfg.get("keywords") or []),
        "keyword_pack_status": cfg.get("keyword_pack_status"),
        "collection_only": collection_only,
        "platform_runs": [r.__dict__ for r in runs],
        "ingest": ingests,
        "dashboard_push": dashboard_push,
        "classified_output": str(classified_path),
        "dashboard_outbox": str(dashboard_outbox_path),
    }
    write_json(status_path, result)
    return result


def _cycle_states(result: dict) -> set[str]:
    return {
        str(row.get("state") or "UNKNOWN")
        for row in (result.get("platform_runs") or [])
    }


def run_forever(cfg: dict) -> None:
    interval = int(cfg.get("interval_seconds", 300))
    if interval < 60:
        raise ValueError("interval_seconds must be >= 60")

    soft_empty_cooldown = max(interval, int(cfg.get("soft_empty_cooldown_seconds", interval)))
    network_cooldown = max(interval, int(cfg.get("network_error_cooldown_seconds", 300)))
    overrun_cooldown = max(30, int(cfg.get("overrun_cooldown_seconds", 60)))

    while True:
        started = time.time()
        result = run_one_cycle(cfg)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        states = _cycle_states(result)

        # Verification/login must return control to the watchdog so it can stop
        # instead of repeatedly hitting the platform while a human challenge is active.
        if states & {"VERIFY_REQUIRED", "LOGIN_REQUIRED"}:
            print("[monitor] official login/verification is required; stop automatic polling until completed manually")
            return

        elapsed = time.time() - started
        if "SOFT_EMPTY" in states:
            # Keep the configured cadence start-to-start.  A clean empty search
            # is not a reason to stop near-realtime discovery for 30+ minutes.
            sleep_for = max(0.0, soft_empty_cooldown - elapsed)
            print(
                f"[monitor] SOFT_EMPTY detected; sleep {sleep_for:.1f}s so the next "
                f"probe starts about {soft_empty_cooldown}s after this cycle started"
            )
        elif "NETWORK_ERROR" in states:
            sleep_for = max(0.0, network_cooldown - elapsed)
            print(
                f"[monitor] NETWORK_ERROR detected; sleep {sleep_for:.1f}s so the next "
                f"retry starts about {network_cooldown}s after this cycle started"
            )
        elif elapsed < interval:
            # Five-minute real-time target is start-to-start, not
            # 'finish a crawl and then wait another five minutes'.
            sleep_for = interval - elapsed
            print(
                f"[monitor] realtime cadence: cycle took {elapsed:.1f}s; "
                f"sleep {sleep_for:.1f}s so next cycle starts about {interval}s after this one"
            )
        else:
            # Never overlap collectors or instantly hammer the platform when a
            # full/deep crawl itself exceeds the five-minute target. Record the
            # SLA miss and allow a short quiet period before continuing.
            sleep_for = overrun_cooldown
            print(
                f"[monitor] realtime SLA miss: cycle took {elapsed:.1f}s > {interval}s; "
                f"do not overlap collectors; cooldown {sleep_for:.1f}s before the next cycle"
            )
        time.sleep(sleep_for)
