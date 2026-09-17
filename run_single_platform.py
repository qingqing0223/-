from __future__ import annotations

import argparse
import json
from pathlib import Path

from monitor.orchestrator import load_config, run_forever, run_one_cycle

PLATFORMS = {"xhs", "dy", "wb", "ks", "bili", "tieba", "zhihu"}


def _install_kuaishou_unknown_comment_queue_fallback() -> None:
    """Allow bounded realtime Kuaishou detail probing when search rows expose no count.

    The current Kuaishou search JSONL can contain ``comment_count`` but leave it at
    zero even for videos whose comments are retrievable.  The shared queue already
    records every discovered identifier, but its normal selector only deep-crawls
    items with a positive visible comment count.  For Kuaishou only, mark such
    count-less discoveries with an explicit ``comment_count_unknown`` signal and a
    synthetic queue priority of 1.  This value is queue-internal; it is never
    written back as a claimed platform comment count.

    The existing realtime_detail_max_items_per_cycle / batch-size / refresh limits
    remain in force, so this does not turn discovery into an unbounded comment scan.
    """
    import monitor.crawler_runner as crawler_runner

    if getattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback", False):
        return

    original_update = crawler_runner._update_queue_from_content

    def update_with_kuaishou_fallback(platform: str, content_files: list[Path], queue: dict) -> None:
        original_update(platform, content_files, queue)
        if platform != "ks":
            return
        for item in (queue.get("items") or {}).values():
            if not isinstance(item, dict):
                continue
            visible = int(item.get("visible_comment_count") or 0)
            if visible > 0:
                item["queue_signal"] = "visible_comment_count"
                item["comment_count_unknown"] = False
                continue
            # Queue-only signal: do not treat this as a real platform count.
            item["visible_comment_count"] = 1
            item["queue_signal"] = "kuaishou_unknown_comment_count"
            item["comment_count_unknown"] = True

    crawler_runner._update_queue_from_content = update_with_kuaishou_fallback
    crawler_runner._promotion_week_ks_unknown_count_fallback = True


def main():
    parser = argparse.ArgumentParser(description="Run one platform only, using the shared monitoring config.")
    parser.add_argument("--platform", required=True, choices=sorted(PLATFORMS))
    parser.add_argument("--config", default="config/monitoring.windows.json")
    parser.add_argument("--keyword", action="append", default=[], help="Override configured keywords; repeat for multiple keywords")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    if args.platform == "ks":
        _install_kuaishou_unknown_comment_queue_fallback()

    cfg = load_config(Path(args.config))
    configured_codes = {str(p.get("code") or "") for p in cfg.get("platforms", [])}
    if args.platform not in configured_codes:
        raise SystemExit(
            f"Platform {args.platform!r} is supported by the runner but missing from {args.config}. "
            "Pull the latest config or add the platform entry first."
        )

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
