from __future__ import annotations

from pathlib import Path
import os
import signal
import subprocess
import time


# Realtime discovery is the five-minute SLA. Historical exhaustive backfill is
# intentionally separate. These values bound only the realtime detail phase and
# can be overridden in the local monitoring config with
# <platform>_realtime_detail_budget_seconds / _candidate_timeout_seconds /
# _max_comments_per_video.
DEFAULT_POLICIES = {
    "xhs": {"budget": 55, "candidate_timeout": 45, "comment_cap": 100},
    "dy": {"budget": 70, "candidate_timeout": 105, "comment_cap": 200},
    "bili": {"budget": 70, "candidate_timeout": 100, "comment_cap": 20},
    "wb": {"budget": 50, "candidate_timeout": 40, "comment_cap": 100},
    "toutiao": {"budget": 105, "candidate_timeout": 60, "comment_cap": 100},
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


def _terminate_process_tree(proc: subprocess.Popen) -> None:
    """Terminate a timed-out crawler and its descendants.

    subprocess.run(timeout=...) can kill only the immediate launcher process on
    Windows. MediaCrawler is started through `uv run`, so the Python crawler can
    otherwise survive as an orphan and continue writing JSONL after rollback.
    """
    if proc.poll() is not None:
        return

    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

    try:
        proc.wait(timeout=10)
    except Exception:
        pass


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
        # Bilibili student configs created before the realtime fix may still
        # contain bili_realtime_max_comments_per_video=300. Direct --once runs do
        # not pass through the config-upgrade PowerShell wrapper, so clamp Bilibili
        # realtime detail here as a code-level invariant rather than trusting a
        # potentially stale local value.
        if platform == "bili":
            comment_cap = min(comment_cap, 20)
        min_start_remaining = max(10, min(int(cfg.get("realtime_detail_min_start_remaining_seconds", 30)), 60))

        started = time.monotonic()
        attempted: list[str] = []
        successful: list[str] = []
        empty: list[str] = []
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

            if platform == "toutiao":
                repo_root = Path(__file__).resolve().parents[1]
                profile_dir = Path(cfg["data_root"]) / "state" / "toutiao_browser_profile"
                cmd = [
                    "uv", "run", "--project", str(cfg["media_crawler_root"]),
                    "python", str(repo_root / "scripts" / "toutiao_crawler.py"),
                    "--mode", "detail",
                    "--specified-id", identifier,
                    "--save-data-path", str(output_dir),
                    "--profile-dir", str(profile_dir),
                    "--get-comment", "yes",
                    "--max-comments", str(comment_cap),
                ]
                detail_cwd = str(repo_root)
            else:
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
                detail_cwd = cfg["media_crawler_root"]

            snapshot = _snapshot_jsonl(output_dir)
            attempted.append(identifier)
            with stdout_log.open("a", encoding="utf-8") as out, stderr_log.open("a", encoding="utf-8") as err:
                out.write(
                    f"\n[monitor] {platform.upper()}_REALTIME_DETAIL "
                    f"candidate={len(attempted)}/{len(candidates)} soft_budget_remaining={int(max(0, remaining))}s "
                    f"candidate_timeout={candidate_timeout}s comment_cap={comment_cap}\n"
                )
                child_env = None
                if platform == "bili":
                    child_env = os.environ.copy()
                    child_env["PROMOTION_WEEK_BILI_REALTIME_DETAIL"] = "1"
                    child_env["PROMOTION_WEEK_BILI_SUBCOMMENT_ROOT_CAP"] = str(
                        max(0, min(_policy_value(cfg, platform, "subcomment_root_cap", 2), 10))
                    )
                    child_env["PROMOTION_WEEK_BILI_SUBCOMMENT_PAGE_CAP"] = str(
                        max(0, min(_policy_value(cfg, platform, "subcomment_page_cap", 1), 5))
                    )

                popen_kwargs = {
                    "cwd": detail_cwd,
                    "stdout": out,
                    "stderr": err,
                    "text": True,
                    "env": child_env,
                }
                if os.name == "nt":
                    popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                else:
                    popen_kwargs["start_new_session"] = True

                proc = subprocess.Popen(cmd, **popen_kwargs)
                try:
                    proc.wait(timeout=candidate_timeout)
                except subprocess.TimeoutExpired:
                    _terminate_process_tree(proc)
                    _rollback_jsonl(output_dir, snapshot)
                    failed.append(identifier)
                    if first_failure_rc is None:
                        first_failure_rc = 124
                    out.write(
                        f"[monitor] {platform.upper()}_REALTIME_DETAIL_CANDIDATE_TIMEOUT "
                        "process_tree_terminated=yes; partial_jsonl_rolled_back=yes; "
                        "candidate_remains_retryable=yes\n"
                    )
                    continue

            if proc.returncode == 0:
                comment_growth = False
                if platform == "toutiao":
                    after_snapshot = _snapshot_jsonl(output_dir)
                    for path, size in after_snapshot.items():
                        if "comment" not in path.name.lower():
                            continue
                        if size > int(snapshot.get(path, 0)):
                            comment_growth = True
                            break
                else:
                    comment_growth = True

                if comment_growth:
                    successful.append(identifier)
                    with stdout_log.open("a", encoding="utf-8") as out:
                        out.write(f"[monitor] {platform.upper()}_REALTIME_DETAIL_CANDIDATE_SUCCESS comments_persisted=yes\n")
                else:
                    empty.append(identifier)
                    with stdout_log.open("a", encoding="utf-8") as out:
                        out.write(
                            f"[monitor] {platform.upper()}_REALTIME_DETAIL_CANDIDATE_EMPTY "
                            "rc=0 comments_persisted=no; continuing_with_next_candidate=yes\n"
                        )
            else:
                _rollback_jsonl(output_dir, snapshot)
                failed.append(identifier)
                if first_failure_rc is None:
                    first_failure_rc = proc.returncode

                access_guard = False
                if platform in {"wb", "xhs", "toutiao"}:
                    tail = crawler_runner._tail_text(stdout_log, stderr_log)
                    tokens = (
                        "weibo_verify_required",
                        "xhs_verify_required",
                        "toutiao_verify_required",
                        "captcha",
                        "security verification",
                        "验证码",
                        "安全验证",
                    )
                    access_guard = any(token in tail for token in tokens)

                with stdout_log.open("a", encoding="utf-8") as out:
                    if access_guard:
                        guard_name = {"wb": "WB", "xhs": "XHS", "toutiao": "TOUTIAO"}.get(platform, platform.upper())
                        out.write(
                            f"[monitor] {guard_name}_REALTIME_ACCESS_GUARD_STOP "
                            f"rc={proc.returncode}; no_more_detail_requests_this_cycle=yes; "
                            "candidate_remains_retryable=yes\n"
                        )
                    else:
                        out.write(
                            f"[monitor] {platform.upper()}_REALTIME_DETAIL_CANDIDATE_FAILED "
                            f"rc={proc.returncode}; partial_jsonl_rolled_back=yes; continuing_with_next_candidate=yes\n"
                        )
                if access_guard:
                    break

        setattr(crawler_runner, "_promotion_week_last_detail_outcome", {
            "platform": platform,
            "requested": list(candidates),
            "attempted": attempted,
            "successful": successful,
            "empty": empty,
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
                empty = list(outcome.get("empty") or [])
                failed = list(outcome.get("failed") or [])
                if successful:
                    original_mark(queue, successful, True)
                if empty:
                    original_mark(queue, empty, False)
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
