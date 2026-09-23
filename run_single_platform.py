from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from monitor.orchestrator import load_config, run_forever, run_one_cycle

PLATFORMS = {"xhs", "dy", "wb", "ks", "bili", "toutiao", "zhihu"}


def _install_kuaishou_unknown_comment_queue_fallback() -> None:
    """Install the Kuaishou realtime comment policy.

    Search stays discovery-only. New videos enter the bounded deep-comment queue
    even when Kuaishou reports a zero/unknown public comment count.

    There is intentionally no preflight that requires an already-running browser
    on 127.0.0.1:9222. The pinned MediaCrawler can launch its own CDP browser
    when CDP_CONNECT_EXISTING=False and its Kuaishou core falls back to standard
    Playwright if CDP launch fails.
    """
    import monitor.crawler_runner as crawler_runner
    from monitor.final_realtime_policy import (
        _rollback_jsonl,
        _snapshot_jsonl,
        _terminate_process_tree,
    )

    if getattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback", False):
        return

    original_update = crawler_runner._update_queue_from_content
    original_detail = crawler_runner._run_detail_comment_recovery
    original_mark = crawler_runner._mark_queue_batch

    def store_outcome(requested, attempted, successful, empty, failed):
        setattr(crawler_runner, "_promotion_week_last_detail_outcome", {
            "platform": "ks",
            "requested": list(requested),
            "attempted": list(attempted),
            "successful": list(successful),
            "empty": list(empty),
            "failed": list(failed),
        })

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
            # Queue-only signal. Do not write a fabricated count to persisted data.
            # Kuaishou has been observed to show 0 while comments are still retrievable.
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
                cfg, platform, candidates, output_dir, stdout_log, stderr_log,
                batch_size=batch_size,
            )
        if not candidates:
            store_outcome([], [], [], [], [])
            return 0, 0

        budget_seconds = max(
            30, min(int(cfg.get("kuaishou_realtime_detail_budget_seconds", 120)), 180)
        )
        candidate_timeout = max(
            20, min(int(cfg.get("kuaishou_realtime_candidate_timeout_seconds", 60)), 150)
        )
        realtime_comment_cap = max(
            20, min(int(cfg.get("kuaishou_realtime_max_comments_per_video", 300)), 2000)
        )
        deadline = time.monotonic() + budget_seconds

        attempted: list[str] = []
        successful: list[str] = []
        empty: list[str] = []
        failed: list[str] = []
        first_failure_rc: int | None = None

        for identifier in candidates:
            remaining = deadline - time.monotonic()
            if remaining <= 10:
                with stdout_log.open("a", encoding="utf-8") as out:
                    out.write(
                        "\n[monitor] KUAISHOU_REALTIME_DETAIL_SOFT_BUDGET_EXHAUSTED "
                        "next_candidate_stays_pending=yes\n"
                    )
                break

            timeout_seconds = max(10, min(candidate_timeout, int(remaining)))
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

            snapshot = _snapshot_jsonl(output_dir)
            attempted.append(identifier)
            with stdout_log.open("a", encoding="utf-8") as out, stderr_log.open("a", encoding="utf-8") as err:
                out.write(
                    f"\n[monitor] KUAISHOU_REALTIME_DETAIL candidate={len(attempted)}/{len(candidates)} "
                    f"budget_remaining={int(remaining)}s candidate_timeout={timeout_seconds}s "
                    f"comment_cap={realtime_comment_cap} external_cdp_preflight=no\n"
                )
                popen_kwargs = {
                    "cwd": cfg["media_crawler_root"],
                    "stdout": out,
                    "stderr": err,
                    "text": True,
                }
                if os.name == "nt":
                    popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                else:
                    popen_kwargs["start_new_session"] = True

                proc = subprocess.Popen(cmd, **popen_kwargs)
                try:
                    proc.wait(timeout=timeout_seconds)
                except subprocess.TimeoutExpired:
                    _terminate_process_tree(proc)
                    _rollback_jsonl(output_dir, snapshot)
                    failed.append(identifier)
                    if first_failure_rc is None:
                        first_failure_rc = 124
                    out.write(
                        "[monitor] KUAISHOU_REALTIME_DETAIL_CANDIDATE_TIMEOUT "
                        "process_tree_terminated=yes; partial_jsonl_rolled_back=yes; "
                        "candidate_remains_retryable=yes\n"
                    )
                    continue

            if proc.returncode != 0:
                _rollback_jsonl(output_dir, snapshot)
                failed.append(identifier)
                if first_failure_rc is None:
                    first_failure_rc = proc.returncode
                with stdout_log.open("a", encoding="utf-8") as out:
                    out.write(
                        f"[monitor] KUAISHOU_REALTIME_DETAIL_CANDIDATE_FAILED rc={proc.returncode}; "
                        "partial_jsonl_rolled_back=yes; continuing_with_next_candidate=yes\n"
                    )
                continue

            after = _snapshot_jsonl(output_dir)
            comment_growth = any(
                "comment" in path.name.lower() and size > int(snapshot.get(path, 0))
                for path, size in after.items()
            )
            if comment_growth:
                successful.append(identifier)
                with stdout_log.open("a", encoding="utf-8") as out:
                    out.write(
                        "[monitor] KUAISHOU_REALTIME_DETAIL_CANDIDATE_SUCCESS "
                        "comments_persisted=yes\n"
                    )
            else:
                empty.append(identifier)
                with stdout_log.open("a", encoding="utf-8") as out:
                    out.write(
                        "[monitor] KUAISHOU_REALTIME_DETAIL_CANDIDATE_EMPTY "
                        "rc=0 comments_persisted=no; candidate_remains_retryable=yes\n"
                    )

        store_outcome(candidates, attempted, successful, empty, failed)
        if successful:
            return 0, len(attempted)
        if first_failure_rc is not None:
            return first_failure_rc, len(attempted)
        return 0, len(attempted)

    def precise_queue_mark(queue: dict, candidates: list[str], success: bool) -> None:
        outcome = getattr(crawler_runner, "_promotion_week_last_detail_outcome", None)
        if isinstance(outcome, dict) and outcome.get("platform") == "ks":
            if list(outcome.get("requested") or []) == list(candidates):
                successful = list(outcome.get("successful") or [])
                empty = list(outcome.get("empty") or [])
                failed = list(outcome.get("failed") or [])
                if successful:
                    original_mark(queue, successful, True)
                if empty:
                    original_mark(queue, empty, False)
                if failed:
                    original_mark(queue, failed, False)
                setattr(crawler_runner, "_promotion_week_last_detail_outcome", None)
                return
        original_mark(queue, candidates, success)

    crawler_runner._update_queue_from_content = update_with_kuaishou_fallback
    crawler_runner._run_detail_comment_recovery = bounded_kuaishou_detail
    crawler_runner._mark_queue_batch = precise_queue_mark
    crawler_runner._promotion_week_ks_unknown_count_fallback = True

def _install_douyin_realtime_policy() -> None:
    """Bound and isolate Douyin deep-comment work inside the five-minute cycle.

    Search remains discovery-only in realtime mode. Comment-bearing videos are
    selected by the shared persistent queue. Each detail candidate runs in its own
    subprocess so one timeout/login/API failure cannot abort all remaining videos.
    """
    import monitor.crawler_runner as crawler_runner

    if getattr(crawler_runner, "_promotion_week_dy_realtime_policy", False):
        return

    original_detail = crawler_runner._run_detail_comment_recovery

    def bounded_douyin_detail(
        cfg: dict,
        platform: str,
        candidates: list[str],
        output_dir: Path,
        stdout_log: Path,
        stderr_log: Path,
        *,
        batch_size: int | None = None,
    ) -> tuple[int | None, int]:
        if platform != "dy" or not bool(cfg.get("realtime_mode", False)):
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

        budget_seconds = max(30, min(int(cfg.get("douyin_realtime_detail_budget_seconds", 120)), 180))
        realtime_comment_cap = max(20, min(int(cfg.get("douyin_realtime_max_comments_per_video", 300)), 2000))
        deadline = time.monotonic() + budget_seconds
        attempts = 0
        success_count = 0
        first_failure_rc: int | None = None

        for identifier in candidates:
            remaining = deadline - time.monotonic()
            if remaining <= 5:
                with stdout_log.open("a", encoding="utf-8") as out:
                    out.write("\n[monitor] DOUYIN_REALTIME_DETAIL_BUDGET_EXHAUSTED before next candidate\n")
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
                    f"\n[monitor] DOUYIN_REALTIME_DETAIL candidate={attempts + 1}/{len(candidates)} "
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
                        "\n[monitor] DOUYIN_REALTIME_DETAIL_BUDGET_EXHAUSTED "
                        "partial_rows_preserved=yes\n"
                    )
                    attempts += 1
                    break

            attempts += 1
            if proc.returncode == 0:
                success_count += 1
                with stdout_log.open("a", encoding="utf-8") as out:
                    out.write("[monitor] DOUYIN_REALTIME_DETAIL_CANDIDATE_SUCCESS\n")
                continue

            if first_failure_rc is None:
                first_failure_rc = proc.returncode
            with stdout_log.open("a", encoding="utf-8") as out:
                out.write(
                    f"[monitor] DOUYIN_REALTIME_DETAIL_CANDIDATE_FAILED rc={proc.returncode}; "
                    "continuing_with_next_candidate=yes\n"
                )

        if success_count > 0:
            return 0, attempts
        if first_failure_rc is not None:
            return first_failure_rc, attempts
        return 0, attempts

    crawler_runner._run_detail_comment_recovery = bounded_douyin_detail
    crawler_runner._promotion_week_dy_realtime_policy = True


def _install_weibo_realtime_policy() -> None:
    """Bound Weibo deep-comment work and stop immediately on anti-abuse signals."""
    import monitor.crawler_runner as crawler_runner

    if getattr(crawler_runner, "_promotion_week_wb_realtime_policy", False):
        return
    # The final student wrapper installs the newer shared atomic realtime policy
    # first. Do not replace that rollback-aware implementation.
    if getattr(crawler_runner, "_promotion_week_final_realtime_policy_wb", False):
        return

    original_detail = crawler_runner._run_detail_comment_recovery

    def bounded_weibo_detail(
        cfg: dict,
        platform: str,
        candidates: list[str],
        output_dir: Path,
        stdout_log: Path,
        stderr_log: Path,
        *,
        batch_size: int | None = None,
    ) -> tuple[int | None, int]:
        if platform != "wb" or not bool(cfg.get("realtime_mode", False)):
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

        budget_seconds = max(30, min(int(cfg.get("wb_realtime_detail_budget_seconds", 55)), 90))
        candidate_timeout = max(15, min(int(cfg.get("wb_realtime_candidate_timeout_seconds", 35)), 60))
        realtime_comment_cap = max(20, min(int(cfg.get("wb_realtime_max_comments_per_video", 100)), 300))
        deadline = time.monotonic() + budget_seconds
        attempts = 0
        success_count = 0
        first_failure_rc: int | None = None

        for identifier in candidates:
            remaining = deadline - time.monotonic()
            if remaining <= 5:
                with stdout_log.open("a", encoding="utf-8") as out:
                    out.write("\n[monitor] WB_REALTIME_DETAIL_BUDGET_EXHAUSTED before next candidate\n")
                break

            cmd = [
                "uv", "run", "main.py",
                "--platform", platform,
                "--lt", cfg.get("login_type", "qrcode"),
                "--type", "detail",
                "--specified_id", identifier,
                "--max_concurrency_num", "1",
                "--get_comment", "yes",
                "--get_sub_comment", str(cfg.get("get_sub_comment", "yes")),
                "--save_data_option", cfg.get("save_data_option", "jsonl"),
                "--save_data_path", str(output_dir),
                "--max_comments_count_singlenotes", str(realtime_comment_cap),
            ]
            env = os.environ.copy()
            env["PROMOTION_WEEK_WB_REALTIME"] = "1"
            timeout_seconds = max(5, min(int(remaining), candidate_timeout))

            with stdout_log.open("a", encoding="utf-8") as out, stderr_log.open("a", encoding="utf-8") as err:
                out.write(
                    f"\n[monitor] WB_REALTIME_DETAIL candidate={attempts + 1}/{len(candidates)} "
                    f"budget_remaining={int(remaining)}s candidate_timeout={timeout_seconds}s "
                    f"comment_cap={realtime_comment_cap}\n"
                )
                try:
                    proc = subprocess.run(
                        cmd,
                        cwd=cfg["media_crawler_root"],
                        stdout=out,
                        stderr=err,
                        text=True,
                        env=env,
                        timeout=timeout_seconds,
                    )
                except subprocess.TimeoutExpired:
                    out.write(
                        "\n[monitor] WB_REALTIME_DETAIL_CANDIDATE_TIMEOUT "
                        "partial_rows_preserved=yes\n"
                    )
                    attempts += 1
                    continue

            attempts += 1
            recent = crawler_runner._tail_text(stdout_log, stderr_log, max_chars=6000)
            if "weibo_verify_required" in recent or "wb_detail_verify_stop" in recent:
                with stdout_log.open("a", encoding="utf-8") as out:
                    out.write("[monitor] WB_REALTIME_DETAIL_VERIFY_STOP automatic retries disabled\n")
                return proc.returncode if proc.returncode not in (0, None) else 86, attempts

            if proc.returncode == 0:
                success_count += 1
                with stdout_log.open("a", encoding="utf-8") as out:
                    out.write("[monitor] WB_REALTIME_DETAIL_CANDIDATE_SUCCESS\n")
                continue

            if first_failure_rc is None:
                first_failure_rc = proc.returncode
            with stdout_log.open("a", encoding="utf-8") as out:
                out.write(
                    f"[monitor] WB_REALTIME_DETAIL_CANDIDATE_FAILED rc={proc.returncode}; "
                    "continuing_with_next_candidate=yes\n"
                )

        # Local time-budget exhaustion is not a platform/network failure. Any JSONL
        # already persisted remains valid; unfinished queue items are eligible again
        # after the normal refresh interval.
        if success_count > 0:
            return 0, attempts
        if first_failure_rc is not None:
            return first_failure_rc, attempts
        return 0, attempts

    crawler_runner._run_detail_comment_recovery = bounded_weibo_detail
    crawler_runner._promotion_week_wb_realtime_policy = True


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
    elif args.platform == "dy":
        _install_douyin_realtime_policy()
    elif args.platform == "wb":
        _install_weibo_realtime_policy()

    cfg = load_config(Path(args.config))

    if args.platform == "wb":
        cfg["collection_only"] = True

    if args.platform == "ks" and bool(cfg.get("realtime_mode", False)):
        # Kuaishou returns a fixed page of up to 20 results per keyword.
        # Slice each page so all six keywords leave room for deep comments.
        cfg["ks_realtime_discovery_max_notes_count"] = 20
        cfg["ks_realtime_items_per_keyword"] = min(
            6, max(2, int(cfg.get("ks_realtime_items_per_keyword", 4)))
        )
        cfg["ks_realtime_search_timeout_seconds"] = min(
            150, max(75, int(cfg.get("ks_realtime_search_timeout_seconds", 120)))
        )
        cfg["ks_realtime_detail_max_items_per_cycle"] = min(
            6, max(2, int(cfg.get("ks_realtime_detail_max_items_per_cycle", 4)))
        )
        cfg["kuaishou_realtime_detail_budget_seconds"] = min(
            120, max(75, int(cfg.get("kuaishou_realtime_detail_budget_seconds", 105)))
        )
        cfg["kuaishou_realtime_candidate_timeout_seconds"] = min(
            60, max(30, int(cfg.get("kuaishou_realtime_candidate_timeout_seconds", 45)))
        )
        cfg["kuaishou_realtime_max_comments_per_video"] = min(
            300, max(50, int(cfg.get("kuaishou_realtime_max_comments_per_video", 200)))
        )
        try:
            configured_classifier = int(cfg.get("classifier_concurrency", 4))
        except Exception:
            configured_classifier = 4
        cfg["classifier_concurrency"] = max(configured_classifier, 12)

    if args.platform == "dy" and bool(cfg.get("realtime_mode", False)):
        # Keep Douyin's live loop on a start-to-start five-minute cadence.
        # Historical exhaustive crawling remains a separate backfill job.
        try:
            configured_discovery = int(cfg.get("realtime_discovery_max_notes_count", 20))
        except Exception:
            configured_discovery = 20
        cfg["realtime_discovery_max_notes_count"] = max(10, min(configured_discovery, 20))
        try:
            configured_classifier = int(cfg.get("classifier_concurrency", 4))
        except Exception:
            configured_classifier = 4
        cfg["classifier_concurrency"] = max(configured_classifier, 12)

    if args.platform == "xhs" and bool(cfg.get("realtime_mode", False)):
        cfg["xhs_realtime_discovery_max_notes_count"] = 20
        cfg["xhs_realtime_items_per_keyword"] = max(
            1, min(int(cfg.get("xhs_realtime_items_per_keyword", 5)), 10)
        )
        cfg["xhs_realtime_search_timeout_seconds"] = min(
            150, max(60, int(cfg.get("xhs_realtime_search_timeout_seconds", 120)))
        )
        cfg["xhs_realtime_detail_max_items_per_cycle"] = min(
            2, max(1, int(cfg.get("xhs_realtime_detail_max_items_per_cycle", 2)))
        )
        cfg["xhs_realtime_detail_budget_seconds"] = min(
            60, max(30, int(cfg.get("xhs_realtime_detail_budget_seconds", 55)))
        )
        cfg["xhs_realtime_candidate_timeout_seconds"] = min(
            60, max(20, int(cfg.get("xhs_realtime_candidate_timeout_seconds", 45)))
        )
        cfg["xhs_realtime_max_comments_per_video"] = min(
            100, max(20, int(cfg.get("xhs_realtime_max_comments_per_video", 100)))
        )
        cfg["network_error_cooldown_seconds"] = max(
            600, int(cfg.get("network_error_cooldown_seconds", 300))
        )
        cfg["overrun_cooldown_seconds"] = max(
            120, int(cfg.get("overrun_cooldown_seconds", 60))
        )
        try:
            configured_classifier = int(cfg.get("classifier_concurrency", 4))
        except Exception:
            configured_classifier = 4
        cfg["classifier_concurrency"] = max(configured_classifier, 12)

    if args.platform == "toutiao" and bool(cfg.get("realtime_mode", False)):
        cfg["toutiao_realtime_discovery_max_notes_count"] = min(
            20, max(5, int(cfg.get("toutiao_realtime_discovery_max_notes_count", 12)))
        )
        cfg["toutiao_realtime_search_timeout_seconds"] = min(
            240, max(90, int(cfg.get("toutiao_realtime_search_timeout_seconds", 180)))
        )
        cfg["toutiao_realtime_detail_max_items_per_cycle"] = min(
            4, max(1, int(cfg.get("toutiao_realtime_detail_max_items_per_cycle", 4)))
        )
        cfg["toutiao_realtime_detail_budget_seconds"] = min(
            120, max(60, int(cfg.get("toutiao_realtime_detail_budget_seconds", 105)))
        )
        cfg["toutiao_realtime_candidate_timeout_seconds"] = min(
            90, max(45, int(cfg.get("toutiao_realtime_candidate_timeout_seconds", 60)))
        )
        cfg["toutiao_realtime_max_comments_per_video"] = min(
            100, max(20, int(cfg.get("toutiao_realtime_max_comments_per_video", 100)))
        )
        cfg["network_error_cooldown_seconds"] = max(
            600, int(cfg.get("network_error_cooldown_seconds", 300))
        )
        cfg["overrun_cooldown_seconds"] = max(
            120, int(cfg.get("overrun_cooldown_seconds", 60))
        )
        try:
            configured_classifier = int(cfg.get("classifier_concurrency", 4))
        except Exception:
            configured_classifier = 4
        cfg["classifier_concurrency"] = max(configured_classifier, 12)

    if args.platform == "wb" and bool(cfg.get("realtime_mode", False)):
        # Weibo is more sensitive to repeated requests. Keep discovery bounded,
        # probe only a few comment candidates per cycle, and stop before the next
        # five-minute discovery window rather than retrying aggressively.
        try:
            configured_discovery = int(cfg.get("realtime_discovery_max_notes_count", 20))
        except Exception:
            configured_discovery = 20
        cfg["realtime_discovery_max_notes_count"] = max(10, min(configured_discovery, 20))
        cfg["wb_realtime_discovery_max_notes_count"] = 10
        cfg["wb_realtime_search_timeout_seconds"] = min(
            120, max(60, int(cfg.get("wb_realtime_search_timeout_seconds", 100)))
        )
        cfg["wb_realtime_detail_max_items_per_cycle"] = min(
            2, max(1, int(cfg.get("wb_realtime_detail_max_items_per_cycle", 2)))
        )
        cfg["wb_realtime_detail_budget_seconds"] = min(
            150, max(30, int(cfg.get("wb_realtime_detail_budget_seconds", 150)))
        )
        cfg["wb_realtime_candidate_timeout_seconds"] = min(
            90, max(20, int(cfg.get("wb_realtime_candidate_timeout_seconds", 90)))
        )
        cfg["wb_realtime_max_comments_per_video"] = min(
            100, max(20, int(cfg.get("wb_realtime_max_comments_per_video", 100)))
        )
        # A real transport/risk-control failure should not trigger rapid repeated
        # requests from the student watchdog.
        cfg["network_error_cooldown_seconds"] = max(
            600, int(cfg.get("network_error_cooldown_seconds", 300))
        )
        cfg["overrun_cooldown_seconds"] = max(
            120, int(cfg.get("overrun_cooldown_seconds", 60))
        )
        try:
            configured_classifier = int(cfg.get("classifier_concurrency", 4))
        except Exception:
            configured_classifier = 4
        cfg["classifier_concurrency"] = max(configured_classifier, 12)

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

    if args.platform == "wb" and bool(cfg.get("realtime_mode", False)):
        from monitor.weibo_scope_policy import install_weibo_monitoring_scope_queue_policy

        install_weibo_monitoring_scope_queue_policy(
            cfg["data_root"],
            str(cfg.get("monitoring_start_time") or ""),
        )

    if args.once:
        print(json.dumps(run_one_cycle(cfg), ensure_ascii=False, indent=2))
    else:
        run_forever(cfg)


if __name__ == "__main__":
    main()
