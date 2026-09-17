from __future__ import annotations

from pathlib import Path
import subprocess
import time


# Realtime discovery is the five-minute SLA. Historical exhaustive backfill is
# intentionally separate. These values bound only the realtime detail phase and
# can be overridden in the local monitoring config with
# <platform>_realtime_detail_budget_seconds / _candidate_timeout_seconds /
# _max_comments_per_video.
DEFAULT_POLICIES = {
    "xhs": {"budget": 70, "candidate_timeout": 100, "comment_cap": 200},
    "dy": {"budget": 70, "candidate_timeout": 105, "comment_cap": 200},
    "bili": {"budget": 70, "candidate_timeout": 100, "comment_cap": 300},
    "wb": {"budget": 60, "candidate_timeout": 90, "comment_cap": 200},
    "tieba": {"budget": 60, "candidate_timeout": 90, "comment_cap": 300},
    "zhihu": {"budget": 60, "candidate_timeout": 90, "comment_cap": 200},
}


def _snapshot_jsonl(root: Path) -> dict[Path, int]:
    snapshot: dict[Path, int] = {}
    if not root.exists():
        return snapshot
    for path in root.rglob("*.jsonl"):
        try:
            snapshot[path] = path.stat().st_size
        except OSError:
            pass
    return snapshot


def _rollback_jsonl(root: Path, snapshot: dict[Path, int]) -> None:
    """Rollback only JSONL bytes created by an interrupted detail candidate.

    A hard subprocess timeout can terminate MediaCrawler between field extraction
    and persistence. Keeping those partial rows caused the observed Douyin case
    where comments existed but public IP-region fields were empty. Realtime now
    treats each candidate as an atomic unit: timeout/non-zero exit rolls the JSONL
    files back to their pre-candidate sizes. The candidate stays pending for a
    later cycle; historical backfill remains unaffected.
    """
    current = set(root.rglob("*.jsonl")) if root.exists() else set()
    for path in current:
        if path not in snapshot:
            try:
                path.unlink()
            except OSError:
                pass
            continue
        try:
            old_size = snapshot[path]
            with path.open("r+b") as f:
                f.truncate(old_size)
        except OSError:
            pass


def _policy_value(cfg: dict, platform: str, suffix: str, default: int) -> int:
    value = cfg.get(f"{platform}_realtime_{suffix}", cfg.get(f"realtime_{suffix}", default))
    try:
        return int(value)
    except Exception:
        return int(default)


def install_final_realtime_policy(platform: str) -> None:
    """Install a safe, isolated realtime detail policy for one platform.

    This policy is deliberately not installed for Kuaishou because Kuaishou has a
    separate unknown-comment-count policy and browser recovery path.
    """
    if platform not in DEFAULT_POLICIES:
        return

    import monitor.crawler_runner as crawler_runner

    marker = f"_promotion_week_final_realtime_policy_{platform}"
    if getattr(crawler_runner, marker, False):
        return

    original_detail = crawler_runner._run_detail_comment_recovery
    original_mark = crawler_runner._mark_queue_batch
    defaults = DEFAULT_POLICIES[platform]

    def isolated_detail(
        cfg: dict,
        actual_platform: str,
        candidates: list[str],
        output_dir: Path,
        stdout_log: Path,
        stderr_log: Path,
        *,
        batch_size: int | None = None,
    ) -> tuple[int | None, int]:
        if actual_platform != platform or not bool(cfg.get("realtime_mode", False)):
            return original_detail(
                cfg,
                actual_platform,
                candidates,
                output_dir,
                stdout_log,
                stderr_log,
                batch_size=batch_size,
            )
        if not candidates:
            setattr(crawler_runner, "_promotion_week_last_detail_outcome", {
                "platform": platform,
                "requested": [],
                "attempted": [],
                "successful": [],
                "failed": [],
            })
            return 0, 0

        budget_seconds = max(30, min(
            _policy_value(cfg, platform, "detail_budget_seconds", defaults["budget"]),
            150,
        ))
        candidate_timeout = max(30, min(
            _policy_value(cfg, platform, "candidate_timeout_seconds", defaults["candidate_timeout"]),
            150,
        ))
        comment_cap = max(20, min(
            _policy_value(cfg, platform, "max_comments_per_video", defaults["comment_cap"]),
            2000,
        ))
        min_start_remaining = max(10, min(int(cfg.get("realtime_detail_min_start_remaining_seconds", 30)), 60))

        started = time.monotonic()
        attempted: list[str] = []
        successful: list[str] = []
        failed: list[str] = []
        first_failure_rc: int | None = None

        for identifier in candidates:
            elapsed = time.monotonic() - started
            remaining = budget_seconds - elapsed
            if attempted and remaining < min_start_remaining:
                with stdout_log.open("a", encoding="utf-8") as out:
                    out.write(
                        f"\n[monitor] {platform.upper()}_REALTIME_DETAIL_SOFT_BUDGET_EXHAUSTED "
                        f"remaining={int(remaining)}s; current candidate was allowed to finish; "
                        "next candidate stays pending\n"
                    )
                break

            cmd = [
                "uv", "run", "main.py",
                "--platform", actual_platform,
                "--lt", cfg.get("login_type", "qrcode"),
                "--type", "detail",
                "--specified_id", identifier,
                "--max_concurrency_num", str(cfg.get("max_concurrency_num", 1)),
                "--get_comment", "yes",
                "--get_sub_comment", str(cfg.get("get_sub_comment", "yes")),
                "--save_data_option", cfg.get("save_data_option", "jsonl"),
                "--save_data_path", str(output_dir),
                "--max_comments_count_singlenotes", str(comment_cap),
            ]

            snapshot = _snapshot_jsonl(output_dir)
            attempted.append(identifier)
            with stdout_log.open("a", encoding="utf-8") as out, stderr_log.open("a", encoding="utf-8") as err:
                out.write(
                    f"\n[monitor] {platform.upper()}_REALTIME_DETAIL "
                    f"candidate={len(attempted)}/{len(candidates)} soft_budget_remaining={int(max(0, remaining))}s "
                    f"candidate_timeout={candidate_timeout}s comment_cap={comment_cap}\n"
                )
                try:
                    proc = subprocess.run(
                        cmd,
                        cwd=cfg["media_crawler_root"],
                        stdout=out,
                        stderr=err,
                        text=True,
                        timeout=candidate_timeout,
                    )
                except subprocess.TimeoutExpired:
                    _rollback_jsonl(output_dir, snapshot)
                    failed.append(identifier)
                    if first_failure_rc is None:
                        first_failure_rc = 124
                    out.write(
                        f"[monitor] {platform.upper()}_REALTIME_DETAIL_CANDIDATE_TIMEOUT "
                        "partial_jsonl_rolled_back=yes; candidate_remains_retryable=yes\n"
                    )
                    continue

            if proc.returncode == 0:
                successful.append(identifier)
                with stdout_log.open("a", encoding="utf-8") as out:
                    out.write(f"[monitor] {platform.upper()}_REALTIME_DETAIL_CANDIDATE_SUCCESS\n")
            else:
                _rollback_jsonl(output_dir, snapshot)
                failed.append(identifier)
                if first_failure_rc is None:
                    first_failure_rc = proc.returncode
                with stdout_log.open("a", encoding="utf-8") as out:
                    out.write(
                        f"[monitor] {platform.upper()}_REALTIME_DETAIL_CANDIDATE_FAILED "
                        f"rc={proc.returncode}; partial_jsonl_rolled_back=yes; continuing_with_next_candidate=yes\n"
                    )

        setattr(crawler_runner, "_promotion_week_last_detail_outcome", {
            "platform": platform,
            "requested": list(candidates),
            "attempted": attempted,
            "successful": successful,
            "failed": failed,
        })

        if successful:
            return 0, len(attempted)
        if first_failure_rc is not None:
            return first_failure_rc, len(attempted)
        return 0, len(attempted)

    def precise_queue_mark(queue: dict, candidates: list[str], success: bool) -> None:
        outcome = getattr(crawler_runner, "_promotion_week_last_detail_outcome", None)
        if isinstance(outcome, dict) and outcome.get("platform") == platform:
            requested = list(outcome.get("requested") or [])
            if requested == list(candidates):
                successful = list(outcome.get("successful") or [])
                failed = list(outcome.get("failed") or [])
                if successful:
                    original_mark(queue, successful, True)
                if failed:
                    original_mark(queue, failed, False)
                # Unattempted candidates are deliberately untouched, so they stay
                # eligible in the persistent queue next cycle.
                setattr(crawler_runner, "_promotion_week_last_detail_outcome", None)
                return
        original_mark(queue, candidates, success)

    crawler_runner._run_detail_comment_recovery = isolated_detail
    crawler_runner._mark_queue_batch = precise_queue_mark
    setattr(crawler_runner, marker, True)
