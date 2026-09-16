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


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    return apply_keyword_pack(cfg, path)


def run_one_cycle(cfg: dict) -> dict:
    data_root = Path(cfg["data_root"])
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cycle_root = data_root / "raw_runs" / stamp
    cycle_root.mkdir(parents=True, exist_ok=True)

    state_path = data_root / "state" / "seen_ids.json"
    classified_path = data_root / "classified" / "classified_results.jsonl"
    status_path = data_root / "status" / "latest_status.json"
    dashboard_outbox_path = data_root / "outbox" / "suqi_pending.jsonl"

    enabled = [p for p in cfg["platforms"] if p.get("enabled", True)]
    workers = max(1, int(cfg.get("max_parallel_platforms", 1)))
    monitoring_start_time = str(cfg.get("monitoring_start_time") or "")

    runs = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_platform, cfg, p, cycle_root) for p in enabled]
        for future in as_completed(futures):
            runs.append(future.result())

    ingests = []
    new_classified_rows = []
    include_comments = bool(cfg.get("ingest_comments", False))
    for run in runs:
        # Always inspect the run directory for usable JSONL first. Some upstream
        # platform adapters may return non-zero after already writing valid
        # content/comment pages (for example natural pagination end, transient
        # network failure, or a later-page error). Those partial results must not
        # be discarded.
        files = find_ingest_jsonl(Path(run.output_dir), include_comments=include_comments)

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
                "partial_crawler_result": False,
                "crawler_state": run.state,
                "skipped_reason": "no_ingest_jsonl"
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
            )
            new_classified_rows.extend(summary.pop("_classified_rows", []))
            summary["ingest_comments"] = include_comments
            summary["partial_crawler_result"] = run.status != "ok"
            summary["crawler_state"] = run.state
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

    result = {
        "event_id": cfg.get("event_id"),
        "event_name": cfg.get("event_name"),
        "monitoring_start_time": monitoring_start_time,
        "results_date": cfg.get("results_date"),
        "cycle_finished_at": datetime.now().isoformat(timespec="seconds"),
        "keyword_count": len(cfg.get("keywords") or []),
        "keyword_pack_status": cfg.get("keyword_pack_status"),
        "platform_runs": [r.__dict__ for r in runs],
        "ingest": ingests,
        "dashboard_push": dashboard_push,
        "classified_output": str(classified_path),
        "dashboard_outbox": str(dashboard_outbox_path),
    }
    write_json(status_path, result)
    return result


def run_forever(cfg: dict) -> None:
    interval = int(cfg.get("interval_seconds", 300))
    if interval < 60:
        raise ValueError("interval_seconds must be >= 60")

    while True:
        started = time.time()
        result = run_one_cycle(cfg)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        elapsed = time.time() - started
        sleep_for = max(0, interval - elapsed)
        if elapsed > interval:
            print(
                f"[monitor] cycle took {elapsed:.1f}s, longer than {interval}s. "
                "The next round starts immediately; the requested interval was missed "
                "for this platform/cycle."
            )
        else:
            print(f"[monitor] sleep {sleep_for:.1f}s")
        time.sleep(sleep_for)
