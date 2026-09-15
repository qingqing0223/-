from __future__ import annotations

import argparse
import json
from pathlib import Path

from monitor.orchestrator import load_config, run_forever, run_one_cycle

PLATFORMS = {"xhs", "dy", "wb", "ks"}


def main():
    parser = argparse.ArgumentParser(description="Run one platform only, using the shared monitoring config.")
    parser.add_argument("--platform", required=True, choices=sorted(PLATFORMS))
    parser.add_argument("--config", default="config/monitoring.windows.json")
    parser.add_argument("--keyword", action="append", default=[], help="Override configured keywords; repeat for multiple keywords")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    for p in cfg.get("platforms", []):
        p["enabled"] = p.get("code") == args.platform

    if args.keyword:
        cfg["keywords"] = args.keyword

    root = Path(cfg["data_root"])
    cfg["data_root"] = str(root.parent / f"{root.name}_{args.platform}")
    cfg["max_parallel_platforms"] = 1

    if args.once:
        print(json.dumps(run_one_cycle(cfg), ensure_ascii=False, indent=2))
    else:
        run_forever(cfg)


if __name__ == "__main__":
    main()
