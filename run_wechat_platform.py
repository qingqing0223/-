from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.io_utils import write_json
from wechat.common import append_jsonl

WECHAT_PLATFORMS = ("wechat_mp", "wechat_channels")
HUMAN_ACTION_STATES = {
    "VERIFY_REQUIRED", "LOGIN_REQUIRED", "LOGIN_OR_UI_REQUIRED", "CHANNELS_WINDOW_REQUIRED"
}


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def platform_root(cfg: dict, platform: str) -> Path:
    base = Path(cfg["data_root"])
    return base.parent / f"{base.name}_{platform}"


def _collector(platform: str):
    if platform == "wechat_mp":
        from wechat.mp_sogou import collect_many
        return collect_many
    if platform == "wechat_channels":
        from wechat.channels_rpa import collect_many
        return collect_many
    raise ValueError(platform)


def run_one_cycle(cfg: dict, platform: str) -> dict:
    if platform == "wechat_mp":
        from wechat.mp_pipeline import run_one_cycle as run_mp_cycle
        return run_mp_cycle(cfg)
    from dashboard_adapter.suqi_pusher import deliver_with_outbox
    from monitor.ingest import ingest_and_classify
    started = time.time()
    root = platform_root(cfg, platform)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_dir = root / "raw_runs" / stamp
    raw_file = raw_dir / "search_contents.jsonl"
    state_path = root / "state" / "seen_ids.json"
    classified_path = root / "classified" / "classified_results.jsonl"
    status_path = root / "status" / "latest_status.json"
    dashboard_outbox_path = root / "outbox" / "suqi_pending.jsonl"
    raw_dir.mkdir(parents=True, exist_ok=True)

    keywords = [str(x).strip() for x in cfg.get("keywords", []) if str(x).strip()]
    collect_many = _collector(platform)
    collector_result = collect_many(cfg, keywords)
    records = collector_result.get("records") or []
    if records:
        append_jsonl(raw_file, records)

    monitoring_start_time = str(cfg.get("monitoring_start_time") or "")
    ingest_summary = {
        "platform": platform,
        "monitoring_start_time": monitoring_start_time,
        "new_records": 0,
        "filtered_before_start": 0,
        "classified_records": 0,
        "region_records": 0,
        "region_rate": 0.0,
        "minority_language_records": 0,
        "minority_language_rate": 0.0,
        "language_counts": {},
        "total_seen": 0,
    }
    new_classified_rows: list[dict] = []
    if records:
        ingest_summary = ingest_and_classify(
            platform,
            [raw_file],
            state_path,
            classified_path,
            int(cfg.get("classifier_concurrency", 4)),
            monitoring_start_time=monitoring_start_time,
        )
        new_classified_rows = ingest_summary.pop("_classified_rows", [])

    dashboard_cfg = cfg.get("dashboard", {}) or {}
    dashboard_push = {
        "enabled": bool(dashboard_cfg.get("enabled", False)),
        "sent": 0,
        "ok": None,
        "inserted": 0,
        "skipped": 0,
        "outbox_after": 0,
    }
    if dashboard_push["enabled"]:
        dashboard_push = deliver_with_outbox(
            new_classified_rows,
            ingest_url=str(dashboard_cfg.get("ingest_url", "")),
            outbox_path=dashboard_outbox_path,
            timeout_seconds=int(dashboard_cfg.get("timeout_seconds", 15)),
        )
        dashboard_push["enabled"] = True

    collector_state = str(collector_result.get("status") or "UNKNOWN")
    if collector_state == "SUCCESS":
        run_status = "ok"
        state = "SUCCESS"
        return_code = 0
    elif collector_state in HUMAN_ACTION_STATES:
        run_status = "needs_human"
        state = collector_state
        return_code = 2
    else:
        run_status = "error"
        state = collector_state
        return_code = 1

    elapsed = round(time.time() - started, 2)
    run = {
        "platform": platform,
        "status": run_status,
        "state": state,
        "return_code": return_code,
        "duration_seconds": elapsed,
        "output_dir": str(raw_dir),
        "records_collected": len(records),
        "collector_details": {k: v for k, v in collector_result.items() if k != "records"},
    }

    result = {
        "event_id": cfg.get("event_id"),
        "event_name": cfg.get("event_name"),
        "monitoring_start_time": monitoring_start_time,
        "results_date": cfg.get("results_date"),
        "cycle_finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "keyword_count": len(keywords),
        "platform_runs": [run],
        "ingest": [ingest_summary],
        "dashboard_push": dashboard_push,
        "classified_output": str(classified_path),
        "raw_output": str(raw_file),
        "dashboard_outbox": str(dashboard_outbox_path),
    }
    write_json(status_path, result)
    return result


def run_forever(cfg: dict, platform: str) -> None:
    if platform == "wechat_mp":
        from wechat.mp_pipeline import run_forever as run_mp_forever
        return run_mp_forever(cfg)
    interval_key = "wechat_mp_interval_seconds" if platform == "wechat_mp" else "wechat_channels_interval_seconds"
    interval = max(300, int(cfg.get(interval_key, cfg.get("interval_seconds", 900))))
    while True:
        started = time.time()
        result = run_one_cycle(cfg, platform)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        state = result["platform_runs"][0]["state"]
        if state in HUMAN_ACTION_STATES:
            if state == "CHANNELS_WINDOW_REQUIRED":
                print(
                    "[wechat_channels] 请手动打开微信 -> 视频号并保持视频号独立窗口可见，然后重新运行。"
                    "程序不会绕过微信登录或安全验证。"
                )
            else:
                print(
                    f"[{platform}] Human action is required. Complete the official login/verification, "
                    "then restart this command. No automated bypass is attempted."
                )
            return
        elapsed = time.time() - started
        sleep_for = max(0, interval - elapsed)
        print(f"[{platform}] next cycle in {sleep_for:.1f}s")
        time.sleep(sleep_for)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", required=True, choices=WECHAT_PLATFORMS)
    parser.add_argument("--config", default=str(ROOT / "config" / "monitoring.wechat.windows.json"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--node-id", help="WeChat MP submission node name")
    args = parser.parse_args()

    cfg = load_config(Path(args.config).resolve())
    if args.node_id and args.platform == "wechat_mp":
        cfg["wechat_mp_node_id"] = args.node_id
    if args.once:
        result = run_one_cycle(cfg, args.platform)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(result["platform_runs"][0]["return_code"])
    run_forever(cfg, args.platform)


if __name__ == "__main__":
    main()
