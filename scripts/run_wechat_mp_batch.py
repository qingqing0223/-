"""Human-operated, resumable monitoring batch; export after all searches finish."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wechat.mp_export import atomic_json
from wechat.mp_pipeline import export_state, ingest_result, load_state, validate_config
from wechat.mp_sogou import collect_many


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config/monitoring.wechat.2026-09-21.json"))
    parser.add_argument("--manual-wait-seconds", type=int, default=None,
                        help="-1 waits indefinitely for manual official verification")
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    os.chdir(ROOT)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
    validate_config(cfg)
    cfg.update(wechat_mp_browser_channel="chrome", wechat_mp_search_until_exhausted=True)
    if args.manual_wait_seconds is not None:
        cfg["wechat_mp_manual_verify_wait_seconds"] = args.manual_wait_seconds
    print(f"[wechat_mp] 本批次{len(cfg['keywords'])}个关键词：有头Chrome、人工验证、自动保存断点。", flush=True)
    print(f"[wechat_mp] 发布时间范围：{cfg['monitoring_start_time']} 至 {cfg.get('monitoring_end_time', '未限定')}（含边界）", flush=True)
    result = collect_many(cfg, cfg["keywords"])
    status = ingest_result(cfg, result, export_outputs=False)
    summary = {"monitoring_start_time": cfg["monitoring_start_time"], "monitoring_end_time": cfg.get("monitoring_end_time"),
               "total_candidates": status["total_candidates"], "valid_articles": status["valid_articles"],
               "invalid_articles": status["invalid_articles"], "pending_review_articles": status["pending_review_articles"],
               **{k: v for k, v in result.items() if k != "records"}}
    target = Path(cfg.get("wechat_mp_work_root", "data/wechat_mp")) / "acceptance_summary.json"
    atomic_json(target, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[wechat_mp] 汇总已保存：{target.resolve()}", flush=True)
    if summary.get("search_acceptance_complete"):
        exported = export_state(cfg, load_state(cfg), force=True)
        summary["export"] = exported
        atomic_json(target, summary)
        print(f"[wechat_mp] 全部关键词搜索完成，CSV/JSONL/XLSX及五个JSON数组已生成：{exported['directory']}", flush=True)
    else:
        print("[wechat_mp] 尚未完成全部关键词。已保存原始记录、候选及汇总；重跑同一命令继续。", flush=True)
    return 0 if result["status"] == "SUCCESS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
