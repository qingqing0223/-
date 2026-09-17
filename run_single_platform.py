from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time

from monitor.orchestrator import load_config, run_forever, run_one_cycle

PLATFORMS = {"xhs", "dy", "wb", "ks", "bili", "tieba", "zhihu"}


def _install_kuaishou_unknown_comment_queue_fallback() -> None:
    """Install the Kuaishou-specific five-minute realtime policy.

    Kuaishou search JSONL currently exposes a ``comment_count`` field but may leave
    it at zero even when comments are retrievable.  The fallback therefore lets
    newly discovered Kuaishou videos enter the persistent detail queue even when
    the public count is unknown.  The queue-only priority value is never written
    back as a claimed platform comment count.

    Realtime deep-comment crawling is also given a finite wall-clock budget and a
    realtime per-video comment cap.  Historical backfill remains separate and may
    crawl to natural end; the realtime path must not let a very large thread delay
    the next new-content discovery indefinitely.
    """
    import monitor.crawler_runner as crawler_runner

    if getattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback", False):
        return

    original_update = crawler_runner._update_queue_from_content
    original_detail = crawler_runner._run_detail_comment_recovery

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

    def bounded_kuaishou_detail(
        cfg: dict,
        platform: str,
        candidates: list[str],
        output_dir: Path,
        stdout_log: Path,
        stderr_log: Path,
        *,
        batch_size: int | None = None,
    ) -> tuple[int | None, int]:
        if platform != "ks" or not bool(cfg.get("realtime_mode", False)):
            return original_detail(
                cfg,
                platform,
                candidates,
                output_dir,
                stdout_log,
                stderr_log,
                batch_size=batch_size,
            )
        if not candidates:
            return 0, 0

        # Keep enough headroom for search, ingestion and status writing inside the
        # 300-second realtime target.  Config can tune the budget, but not above 180s.
        budget_seconds = max(30, min(int(cfg.get("kuaishou_realtime_detail_budget_seconds", 120)), 180))
        realtime_comment_cap = max(20, min(int(cfg.get("kuaishou_realtime_max_comments_per_video", 300)), 2000))
        requested_batch = max(1, int(batch_size or cfg.get("realtime_detail_batch_size", 4)))
        effective_batch = min(requested_batch, max(1, int(cfg.get("kuaishou_realtime_detail_batch_size", 2))))
        deadline = time.monotonic() + budget_seconds
        batches = 0

        for start in range(0, len(candidates), effective_batch):
            remaining = deadline - time.monotonic()
            if remaining <= 5:
                with stdout_log.open("a", encoding="utf-8") as out:
                    out.write("\n[monitor] KUAISHOU_REALTIME_DETAIL_BUDGET_EXHAUSTED before next batch\n")
                break

            batch = candidates[start:start + effective_batch]
            cmd = [
                "uv", "run", "main.py",
                "--platform", platform,
                "--lt", cfg.get("login_type", "qrcode"),
                "--type", "detail",
                "--specified_id", ",".join(batch),
                "--max_concurrency_num", str(cfg.get("max_concurrency_num", 1)),
                "--get_comment", "yes",
                "--get_sub_comment", str(cfg.get("get_sub_comment", "yes")),
                "--save_data_option", cfg.get("save_data_option", "jsonl"),
                "--save_data_path", str(output_dir),
                "--max_comments_count_singlenotes", str(realtime_comment_cap),
            ]
            with stdout_log.open("a", encoding="utf-8") as out, stderr_log.open("a", encoding="utf-8") as err:
                out.write(
                    f"\n[monitor] KUAISHOU_REALTIME_DETAIL batch={batches + 1} "
                    f"items={len(batch)} budget_remaining={int(remaining)}s "
                    f"comment_cap={realtime_comment_cap}\n"
                )
                try:
                    proc = subprocess.run(
                        cmd,
                        cwd=cfg["media_crawler_root"],
                        stdout=out,
                        stderr=err,
                        text=True,
                        timeout=max(5, int(remaining)),
                    )
                except subprocess.TimeoutExpired:
                    # Partial JSONL already written by MediaCrawler remains useful.
                    # Treat wall-clock budget exhaustion as a scheduled yield, not a
                    # network failure; the persistent queue becomes eligible again
                    # after the configured refresh interval.
                    out.write("\n[monitor] KUAISHOU_REALTIME_DETAIL_BUDGET_EXHAUSTED partial_rows_preserved=yes\n")
                    batches += 1
                    return 0, batches

            batches += 1
            if proc.returncode != 0:
                return proc.returncode, batches

        return 0, batches

    crawler_runner._update_queue_from_content = update_with_kuaishou_fallback
    crawler_runner._run_detail_comment_recovery = bounded_kuaishou_detail
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
