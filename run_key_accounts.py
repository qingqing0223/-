from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import time

from dashboard_adapter.suqi_pusher import deliver_with_outbox
from monitor.creator_runner import run_creator_platform
from monitor.crawler_runner import find_content_jsonl
from monitor.key_account_ingest import ingest_key_account_snapshot
from monitor.account_info import build_table5_account_rows, write_table5_account_snapshots
from pipeline.io_utils import write_json


PLATFORM_NAMES = {
    "xhs": "小红书",
    "dy": "抖音",
    "ks": "快手",
    "bili": "B站",
    "wb": "微博",
    "toutiao": "今日头条",
    "zhihu": "知乎",
}


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run_cycle(cfg: dict, platform_filter: str | None = None) -> dict:
    accounts = [
        a for a in (cfg.get("accounts") or [])
        if a.get("enabled", False) and str(a.get("creator_id") or "").strip()
    ]
    if platform_filter:
        accounts = [a for a in accounts if a.get("platform") == platform_filter]
    if not accounts:
        return {
            "cycle_finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "ok": False,
            "reason": "no_enabled_accounts",
            "platform": platform_filter,
        }

    grouped: dict[str, list[dict]] = {}
    for account in accounts:
        code = str(account.get("platform") or "").strip()
        if code in PLATFORM_NAMES:
            grouped.setdefault(code, []).append(account)

    base_root = Path(cfg["data_root"])
    results = []
    for platform, items in grouped.items():
        root = base_root.parent / f"{base_root.name}_{platform}"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cycle_root = root / "raw_runs" / stamp
        cycle_root.mkdir(parents=True, exist_ok=True)

        run = run_creator_platform(
            cfg,
            platform=platform,
            platform_name=PLATFORM_NAMES[platform],
            creator_ids=[str(x["creator_id"]) for x in items],
            run_root=cycle_root,
        )

        item = {
            "platform": platform,
            "accounts_requested": len(items),
            "platform_run": run.__dict__,
        }
        if run.status != "ok":
            item["ok"] = False
            item["reason"] = run.state
            results.append(item)
            continue

        files = find_content_jsonl(Path(run.output_dir))
        if not files:
            item["ok"] = False
            item["reason"] = "no_content_jsonl"
            results.append(item)
            continue

        classified_path = root / "classified" / "classified_results.jsonl"
        state_path = root / "state" / "seen_ids.json"
        summary = ingest_key_account_snapshot(
            platform,
            files,
            state_path,
            classified_path,
            concurrency=int(cfg.get("classifier_concurrency", 4)),
            monitoring_start_time=str(cfg.get("monitoring_start_time") or ""),
        )
        push_rows = summary.pop("push_rows")

        raw_account_files = sorted(
            p for p in Path(run.output_dir).rglob("*.jsonl")
            if "account_info" in p.name.lower()
        )
        account_rows = build_table5_account_rows(
            platform,
            items,
            classified_path,
            raw_files=raw_account_files,
        )
        account_snapshot = write_table5_account_snapshots(root, account_rows)

        dashboard_cfg = cfg.get("dashboard") or {}
        dashboard_result = {"enabled": bool(dashboard_cfg.get("enabled", False)), "sent": 0, "ok": None}
        if dashboard_result["enabled"]:
            dashboard_result = deliver_with_outbox(
                push_rows,
                ingest_url=str(dashboard_cfg.get("ingest_url") or ""),
                outbox_path=root / "outbox" / "suqi_pending.jsonl",
                timeout_seconds=int(dashboard_cfg.get("timeout_seconds", 15)),
            )
            dashboard_result["enabled"] = True

        item.update({
            "ok": True,
            "ingest": summary,
            "account_info": account_snapshot,
            "dashboard_push": dashboard_result,
        })
        results.append(item)

        write_json(root / "status" / "latest_status.json", {
            "cycle_finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "mode": "key_account_creator",
            "platform_runs": [run.__dict__],
            "ingest": [summary],
            "account_info": account_snapshot,
            "dashboard_push": dashboard_result,
        })

    return {
        "cycle_finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": "key_account_creator",
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Monitor configured key accounts using MediaCrawler creator mode.")
    parser.add_argument("--config", default="config/key_accounts.json")
    parser.add_argument("--platform", choices=sorted(PLATFORM_NAMES), default=None)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        raise SystemExit(
            f"Config not found: {config_path}. Copy config/key_accounts.example.json to "
            "config/key_accounts.json and fill verified creator IDs first."
        )
    cfg = load_config(config_path)
    interval = max(300, int(cfg.get("interval_seconds", 300)))

    while True:
        started = time.time()
        result = run_cycle(cfg, platform_filter=args.platform)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.once:
            break

        states = [
            str((r.get("platform_run") or {}).get("state") or "")
            for r in result.get("results", [])
        ]
        if any(state in {"VERIFY_REQUIRED", "LOGIN_REQUIRED"} for state in states):
            print("[key-accounts] official login/verification is required; automatic polling stopped.")
            break

        elapsed = time.time() - started
        time.sleep(max(0, interval - elapsed))


if __name__ == "__main__":
    main()
