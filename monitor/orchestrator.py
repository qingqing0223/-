from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import json
import time

from .crawler_runner import run_platform, find_content_jsonl
from .ingest import ingest_and_classify
from pipeline.io_utils import write_json
from dashboard_adapter.suqi_pusher import push_records

def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

def run_one_cycle(cfg: dict) -> dict:
    data_root = Path(cfg["data_root"])
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cycle_root = data_root / "raw_runs" / stamp
    cycle_root.mkdir(parents=True, exist_ok=True)

    state_path = data_root / "state" / "seen_ids.json"
    classified_path = data_root / "classified" / "classified_results.jsonl"
    status_path = data_root / "status" / "latest_status.json"

    enabled = [p for p in cfg["platforms"] if p.get("enabled", True)]
    workers = max(1, int(cfg.get("max_parallel_platforms", 1)))

    runs = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_platform, cfg, p, cycle_root) for p in enabled]
        for future in as_completed(futures):
            runs.append(future.result())

    ingests = []
    new_classified_rows = []
    for run in runs:
        if run.status != "ok":
            ingests.append({
                "platform": run.platform,
                "new_records": 0,
                "classified_records": 0,
                "skipped_reason": f"crawler_{run.status}"
            })
            continue

        files = find_content_jsonl(Path(run.output_dir))
        if not files:
            ingests.append({
                "platform": run.platform,
                "new_records": 0,
                "classified_records": 0,
                "skipped_reason": "no_content_jsonl"
            })
            continue

        try:
            summary = ingest_and_classify(
                run.platform, files, state_path, classified_path,
                int(cfg.get("classifier_concurrency", 4))
            )
            new_classified_rows.extend(summary.pop("_classified_rows", []))
            ingests.append(summary)
        except Exception as exc:
            ingests.append({
                "platform": run.platform,
                "new_records": 0,
                "classified_records": 0,
                "skipped_reason": f"classifier_error:{type(exc).__name__}:{exc}"
            })

    dashboard_cfg = cfg.get("dashboard", {}) or {}
    dashboard_push = {
        "enabled": bool(dashboard_cfg.get("enabled", False)),
        "sent": 0,
        "ok": None,
    }
    if dashboard_push["enabled"]:
        if new_classified_rows:
            dashboard_push = push_records(
                new_classified_rows,
                ingest_url=str(dashboard_cfg.get("ingest_url", "")),
                timeout_seconds=int(dashboard_cfg.get("timeout_seconds", 15)),
            )
            dashboard_push["enabled"] = True
        else:
            dashboard_push.update({"ok": True, "reason": "no_new_records"})

    result = {
        "cycle_finished_at": datetime.now().isoformat(timespec="seconds"),
        "platform_runs": [r.__dict__ for r in runs],
        "ingest": ingests,
        "dashboard_push": dashboard_push,
        "classified_output": str(classified_path),
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
                "The next round starts immediately; true 5-minute four-platform "
                "coverage is not yet proven on this computer."
            )
        else:
            print(f"[monitor] sleep {sleep_for:.1f}s")
        time.sleep(sleep_for)
