"""Re-export the persisted public MP records without a network request."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wechat.mp_pipeline import export_state, load_state

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/monitoring.wechat.windows.json")
    parser.add_argument("--require-complete", action="store_true", help="Refuse final export until all configured real searches finish")
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
    state = load_state(cfg)
    if args.require_complete:
        last = state.get("last_collector", {})
        coverage = last.get("keyword_coverage", {})
        stats = last.get("keyword_stats", {})
        if (not last.get("search_acceptance_complete") or set(coverage) != set(cfg["keywords"])
                or not all(coverage[k] in ("SUCCESS", "NO_RESULTS") and stats.get(k, {}).get("attempted") for k in cfg["keywords"])):
            raise SystemExit("本批次真实搜索尚未全部完成，拒绝生成最终Excel。请先运行人工采集命令。")
    print(json.dumps(export_state(cfg, state, force=True), ensure_ascii=False, indent=2))
