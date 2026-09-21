"""Incremental collection and independent export clocks, isolated from old ingest."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import time

from .common import now_cn
from .mp_export import atomic_json, export_submission, write_jsonl
from .mp_records import START, assess_record, candidate_counts, merge_records


def load_state(cfg: dict) -> dict:
    path = Path(cfg.get("wechat_mp_work_root", "data/wechat_mp")) / "state_v3.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version": 3, "records": []}


def validate_config(cfg: dict) -> None:
    start = datetime.fromisoformat(cfg.get("monitoring_start_time", START))
    if start.tzinfo is None:
        raise ValueError("monitoring_start_time requires timezone")
    if start < datetime.fromisoformat(START):
        raise ValueError("WeChat MP monitoring_start_time must not precede 2026-09-16 +08:00")
    if cfg.get("monitoring_end_time"):
        end = datetime.fromisoformat(cfg["monitoring_end_time"])
        if end.tzinfo is None or end < start:
            raise ValueError("monitoring_end_time requires timezone and must not precede start")
    keywords = cfg.get("keywords", [])
    if not keywords or any(not isinstance(k, str) or not k.strip() for k in keywords) or len(set(keywords)) != len(keywords):
        raise ValueError("WeChat MP requires a nonempty list of distinct keywords")


def export_state(cfg: dict, state: dict, force: bool = False) -> dict:
    records = [assess_record(r, cfg.get("monitoring_start_time", START), cfg.get("keywords"), cfg.get("monitoring_end_time")) for r in state["records"]]
    catalog = json.loads(Path(cfg.get("wechat_mp_key_accounts", "config/key_accounts.wechat_mp.json")).read_text(encoding="utf-8"))
    details = dict(state.get("last_collector", {}))
    details["scope_audit"] = {
        "total_unique": len(records), **candidate_counts(records),
        "review_reasons": dict(Counter(r["invalid_reason"] for r in records if not r["is_valid"])),
    }
    details["keyword_coverage"] = {k: details.get("per_keyword_status", {}).get(k, "NOT_SEARCHED") for k in cfg.get("keywords", [])}
    return export_submission(records, cfg, catalog,
                             now_cn().isoformat(timespec="seconds"), details, force)


def ingest_result(cfg: dict, result: dict, force_export: bool = True, export_outputs: bool = True) -> dict:
    root = Path(cfg.get("wechat_mp_work_root", "data/wechat_mp"))
    stamp = now_cn().strftime("%Y%m%d_%H%M%S_%f")
    rows = result.get("records", [])
    write_jsonl(root / "raw_runs" / stamp / "search_contents.jsonl", rows)
    state = load_state(cfg)
    before = len(state["records"])
    state["records"] = merge_records(state["records"], rows)
    state["records"] = [assess_record(r, cfg.get("monitoring_start_time", START), cfg.get("keywords"), cfg.get("monitoring_end_time")) for r in state["records"]]
    counts = candidate_counts(state["records"])
    details = {k: v for k, v in result.items() if k != "records"}
    details["scope_audit"] = {
        "round_records": len(rows), "total_unique": len(state["records"]), **counts,
        "exclusion_reasons": dict(Counter(r["invalid_reason"] for r in state["records"] if not r["is_valid"])),
    }
    state["last_collector"] = details
    atomic_json(root / "state_v3.json", state)
    excluded = [r for r in state["records"] if not r["is_valid"]]
    write_jsonl(root / "excluded_records.jsonl", excluded)
    write_jsonl(root / "candidates.jsonl", [r for r in state["records"] if r["candidate_eligible"]])
    export = export_state(cfg, state, force_export) if export_outputs else {"deferred": True}
    status = {
        "platform": "wechat_mp", "state": result.get("status", "UNKNOWN"),
        "records_collected": len(rows), "new_unique": len(state["records"]) - before,
        "total_unique": len(state["records"]), **counts,
        "excluded": len(excluded), "filtered_before_start": sum(r["invalid_reason"] == "发布时间早于正式监测开始时间" for r in excluded),
        "collector_details": details, "export": export,
    }
    atomic_json(root / "status/latest_status.json", status)
    return {"platform_runs": [{**status, "return_code": 0 if status["state"] == "SUCCESS" else 2 if status["state"] == "VERIFY_REQUIRED" else 1}], **status}


def run_one_cycle(cfg: dict) -> dict:
    validate_config(cfg)
    from .mp_sogou import collect_many
    return ingest_result(cfg, collect_many(cfg, cfg["keywords"]))


def run_forever(cfg: dict) -> None:
    validate_config(cfg)
    from .mp_sogou import collect_many
    # The collector owns its Playwright thread. The main loop owns state and
    # exports, so slow searches / human verification do not stop export clocks.
    interval = max(1, int(cfg.get("wechat_mp_interval_seconds", 300)))
    next_search = 0.0
    future = None
    export_retry_at = 0.0
    with ThreadPoolExecutor(max_workers=1) as pool:
        while True:
            if future is None and time.monotonic() >= next_search:
                future = pool.submit(collect_many, cfg, cfg["keywords"])
                next_search = time.monotonic() + interval
            if future is not None and future.done():
                try:
                    result = future.result()
                except Exception as exc:
                    result = {"status": "COLLECTOR_ERROR", "records": [], "error": type(exc).__name__}
                future = None
                try:
                    status = ingest_result(cfg, result, force_export=False)
                    print(json.dumps(status, ensure_ascii=False), flush=True)
                except Exception as exc:
                    print(f"[wechat_mp] export/state error: {type(exc).__name__}; retry next tick", flush=True)
                    export_retry_at = time.monotonic() + 60
                if result["status"] == "VERIFY_REQUIRED":
                    print("[wechat_mp] 人工验证未完成，本轮停止。请完成官方验证后重新启动。", flush=True)
                    return
            try:
                state = load_state(cfg)
                if state.get("last_collector") and time.monotonic() >= export_retry_at:
                    export_state(cfg, state)
            except Exception as exc:
                print(f"[wechat_mp] export retry: {type(exc).__name__}", flush=True)
                export_retry_at = time.monotonic() + 60
            time.sleep(1)
