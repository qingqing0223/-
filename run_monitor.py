from __future__ import annotations
import argparse, json
from pathlib import Path
from monitor.orchestrator import load_config, run_one_cycle, run_forever

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/monitoring.windows.json")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    cfg = load_config(Path(args.config))
    if args.once:
        print(json.dumps(run_one_cycle(cfg), ensure_ascii=False, indent=2))
    else:
        run_forever(cfg)

if __name__ == "__main__":
    main()
