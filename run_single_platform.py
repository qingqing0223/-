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
    it at zero even when comments are retrievable. The fallback therefore lets
    newly discovered Kuaishou videos enter the persistent detail queue even when
    the public count is unknown. The queue-only priority value is never written
    back as a claimed platform comment count.

    Realtime deep-comment crawling is also given a finite wall-clock budget and a
    realtime per-video comment cap. Historical backfill remains separate and may
    crawl to natural end; the realtime path must not let a very large thread delay
    the next new-content discovery indefinitely.

    Kuaishou detail subprocesses are intentionally isolated per candidate. A
    transient browser/API failure on one video must not prevent the remaining
    queued videos from being tried in the same realtime budget.
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
        # 300-second realtime target. Config can tune the budget, but not above 180s.
        budget_seconds = max(30, min(int(cfg.get("kuaishou_realtime_detail_budget_seconds", 120)), 180))
        realtime_comment_cap = max(20, min(int(cfg.get("kuaishou_realtime_max_comments_per_video", 300)), 2000))
        deadline = time.monotonic() + budget_seconds
        attempts = 0
        success_count = 0
        first_failure_rc: int | None = None

        # Deliberately isolate each candidate. MediaCrawler launches one detail
        # process per candidate here; a bad/transient video/browser session cannot
        # abort every other candidate in the bounded queue.
        for identifier in candidates:
            remaining = deadline - time.monotonic()
            if remaining <= 5:
                with stdout_log.open("a", encoding="utf-8") as out:
                    out.write("\n[monitor] KUAISHOU_REALTIME_DETAIL_BUDGET_EXHAUSTED before next candidate\n")
                break

            cmd = [
                "uv", "run", "main.py",
                "--platform", platform,
                "--lt", cfg.get("login_type", "qrcode"),
                "--type", "detail",
                "--specified_id", identifier,
                "--max_concurrency_num", str(cfg.get("max_concurrency_num", 1)),
                "--get_comment", "yes",
                "--get_sub_comment", str(cfg.get("get_sub_comment", "yes")),
                "--save_data_option", cfg.get("save_data_option", "jsonl"),
                "--save_data_path", str(output_dir),
                "--max_comments_count_singlenotes", str(realtime_comment_cap),
            ]
            with stdout_log.open("a", encoding="utf-8") as out, stderr_log.open("a", encoding="utf-8") as err:
                out.write(
                    f"\n[monitor] KUAISHOU_REALTIME_DETAIL candidate={attempts + 1}/{len(candidates)} "
                    f"budget_remaining={int(remaining)}s comment_cap={realtime_comment_cap}\n"
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
                    out.write(
                        "\n[monitor] KUAISHOU_REALTIME_DETAIL_BUDGET_EXHAUSTED "
                        "partial_rows_preserved=yes\n"
                    )
                    attempts += 1
                    break

            attempts += 1
            if proc.returncode == 0:
                success_count += 1
                with stdout_log.open("a", encoding="utf-8") as out:
                    out.write("[monitor] KUAISHOU_REALTIME_DETAIL_CANDIDATE_SUCCESS\n")
                continue

            if first_failure_rc is None:
                first_failure_rc = proc.returncode
            with stdout_log.open("a", encoding="utf-8") as out:
                out.write(
                    f"[monitor] KUAISHOU_REALTIME_DETAIL_CANDIDATE_FAILED rc={proc.returncode}; "
                    "continuing_with_next_candidate=yes\n"
                )

        # If at least one isolated candidate completed, keep the cycle alive so
        # persisted comments can be ingested and inspected. Failed candidates stay
        # recoverable on a later refresh cycle through the persistent queue.
        if success_count > 0:
            return 0, attempts
        if first_failure_rc is not None:
            return first_failure_rc, attempts
        return 0, attempts

    crawler_runner._update_queue_from_content = update_with_kuaishou_fallback
    crawler_runner._run_detail_comment_recovery = bounded_kuaishou_detail
    crawler_runner._promotion_week_ks_unknown_count_fallback = True


def _install_kuaishou_precise_failure_classifier() -> None:
    """Avoid false NETWORK_ERROR states caused by recovered transport warnings."""
    import monitor.crawler_runner as crawler_runner

    if getattr(crawler_runner, "_promotion_week_ks_precise_failure_classifier", False):
        return

    original_classify = crawler_runner._classify_state
    explicit_network_markers = (
        "connecttimeout", "readtimeout", "timed out", "timeouterror",
        "err_timed_out", "err_connection_reset", "err_connection_refused",
        "err_network_changed", "connection reset", "connection refused",
        "httpx.connecterror", "httpx.readtimeout", "temporary failure in name resolution",
        "name or service not known", "nodename nor servname", "http 502", "status 502",
        "http 503", "status 503", "http 504", "status 504",
    )

    def classify_precisely(
        return_code,
        stdout_log,
        stderr_log,
        runner_error="",
        *,
        content_row_count=0,
        comment_row_count=0,
        comments_enabled=False,
    ):
        # Once both discovery and comment rows have been durably written, a later
        # isolated detail failure is a partial success, not a reason to discard or
        # hide the usable realtime cycle.
        if not runner_error and content_row_count > 0 and comment_row_count > 0:
            return "PARTIAL_SUCCESS" if return_code not in (0, None) else "SUCCESS"

        state = original_classify(
            return_code,
            stdout_log,
            stderr_log,
            runner_error=runner_error,
            content_row_count=content_row_count,
            comment_row_count=comment_row_count,
            comments_enabled=comments_enabled,
        )
        if state != "NETWORK_ERROR":
            return state

        text = crawler_runner._tail_text(stdout_log, stderr_log)
        if any(marker in text for marker in explicit_network_markers):
            return "NETWORK_ERROR"

        if runner_error:
            return "RUNNER_ERROR"
        if return_code == 0:
            if content_row_count == 0 and comment_row_count == 0:
                return "SOFT_EMPTY"
            if comments_enabled and content_row_count > 0 and comment_row_count == 0:
                return "SUCCESS_NO_COMMENTS"
            return "SUCCESS"
        if return_code is None:
            return "RUNNER_ERROR"
        return "CRAWLER_FAILED"

    crawler_runner._classify_state = classify_precisely
    crawler_runner._promotion_week_ks_precise_failure_classifier = True


def main():
    parser = argparse.ArgumentParser(description="Run one platform only, using the shared monitoring config.")
    parser.add_argument("--platform", required=True, choices=sorted(PLATFORMS))
    parser.add_argument("--config", default="config/monitoring.windows.json")
    parser.add_argument("--keyword", action="append", default=[], help="Override configured keywords; repeat for multiple keywords")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    if args.platform == "ks":
        _install_kuaishou_unknown_comment_queue_fallback()
        _install_kuaishou_precise_failure_classifier()

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
