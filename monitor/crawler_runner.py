from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import subprocess
import time


@dataclass
class PlatformRun:
    platform: str
    platform_name: str
    started_at: str
    finished_at: str
    duration_seconds: float
    return_code: int | None
    output_dir: str
    stdout_log: str
    stderr_log: str
    status: str
    state: str
    error: str = ""
    content_file_count: int = 0
    comment_file_count: int = 0
    content_row_count: int = 0
    comment_row_count: int = 0
    detail_recovery_candidates: int = 0
    detail_recovery_batches: int = 0
    realtime_mode: bool = False
    deep_queue_pending: int = 0


def _tail_text(*paths: Path, max_chars: int = 16000) -> str:
    parts = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            parts.append(text[-max_chars:])
        except Exception:
            pass
    return "\n".join(parts).lower()


def _log_line_has_markers(
    paths: tuple[Path, ...] | list[Path],
    *markers: str,
) -> bool:
    """Scan complete logs for markers that may have fallen outside tail text."""
    needles = tuple(
        str(marker).lower()
        for marker in markers
        if str(marker)
    )

    if not needles:
        return False

    for path in paths:
        try:
            with path.open(
                "r",
                encoding="utf-8",
                errors="replace",
            ) as fh:
                for line in fh:
                    low = line.lower()
                    if all(
                        needle in low
                        for needle in needles
                    ):
                        return True
        except Exception:
            continue

    return False


def _count_jsonl_rows(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        try:
            with path.open("r", encoding="utf-8-sig", errors="replace") as f:
                total += sum(1 for line in f if line.strip())
        except Exception:
            continue
    return total


def _iter_jsonl(paths: list[Path]):
    for path in paths:
        try:
            with path.open("r", encoding="utf-8-sig", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(row, dict):
                        yield row
        except Exception:
            continue


def _as_count(value) -> int:
    if value in (None, ""):
        return 0
    text = str(value).strip().replace(",", "").replace("，", "")
    try:
        if text.endswith("万"):
            return int(float(text[:-1]) * 10000)
        if text.lower().endswith("w"):
            return int(float(text[:-1]) * 10000)
        if text.lower().endswith("k"):
            return int(float(text[:-1]) * 1000)
        return int(float(text))
    except Exception:
        return 0


_COMMENT_COUNT_KEYS = (
    "comment_count", "comments_count", "comment_num", "video_comment",
    "total_comments", "reply_count", "total_replay_num",
)


def _visible_comment_count(row: dict) -> int:
    return max((_as_count(row.get(k)) for k in _COMMENT_COUNT_KEYS), default=0)


def _detail_identifier(platform: str, row: dict) -> str:
    if platform == "xhs":
        return str(row.get("note_url") or row.get("note_id") or "").strip()
    if platform == "dy":
        return str(row.get("aweme_url") or row.get("aweme_id") or "").strip()
    if platform == "ks":
        return str(row.get("video_url") or row.get("photo_url") or row.get("photo_id") or row.get("video_id") or "").strip()
    if platform == "bili":
        return str(row.get("video_url") or row.get("video_id") or row.get("bvid") or "").strip()
    if platform == "wb":
        return str(row.get("note_id") or row.get("id") or row.get("note_url") or "").strip()
    if platform == "toutiao":
        return str(
            row.get("content_url") or row.get("url") or row.get("article_id")
            or row.get("content_id") or ""
        ).strip()
    if platform == "zhihu":
        return str(row.get("content_url") or row.get("content_id") or row.get("url") or row.get("id") or "").strip()
    return ""


def _detail_recovery_candidates(platform: str, content_files: list[Path], max_items: int) -> list[str]:
    candidates = []
    seen = set()
    for row in _iter_jsonl(content_files):
        if _visible_comment_count(row) <= 0:
            continue
        identifier = _detail_identifier(platform, row)
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        candidates.append(identifier)
        if len(candidates) >= max_items:
            break
    return candidates


def _queue_path(cfg: dict, platform: str) -> Path:
    return Path(cfg["data_root"]) / "state" / f"deep_comment_queue_{platform}.json"


def _load_queue(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("items"), dict):
            return data
    except Exception:
        pass
    return {"version": 1, "items": {}}


def _save_queue(path: Path, queue: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _update_queue_from_content(platform: str, content_files: list[Path], queue: dict) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    items = queue.setdefault("items", {})
    for row in _iter_jsonl(content_files):
        identifier = _detail_identifier(platform, row)
        if not identifier:
            continue
        visible = _visible_comment_count(row)
        item = items.setdefault(identifier, {
            "first_seen_at": now,
            "last_seen_at": now,
            "last_deep_crawled_at": "",
            "visible_comment_count": 0,
            "retry_count": 0,
        })
        item["last_seen_at"] = now
        if platform == "toutiao" and str(row.get("comment_count_source") or "") == "render_data":
            # Toutiao RENDER_DATA is article-specific and can safely correct an
            # earlier false-positive whole-page count, including resetting it to 0.
            item["visible_comment_count"] = visible
        else:
            item["visible_comment_count"] = max(int(item.get("visible_comment_count") or 0), visible)


def _select_queue_candidates(queue: dict, max_items: int, refresh_seconds: int) -> list[str]:
    now = time.time()
    eligible = []
    for identifier, item in (queue.get("items") or {}).items():
        visible = int(item.get("visible_comment_count") or 0)
        if visible <= 0:
            continue
        last = str(item.get("last_deep_crawled_at") or "")
        last_ts = 0.0
        if last:
            try:
                last_ts = datetime.fromisoformat(last.replace("Z", "+00:00")).timestamp()
            except Exception:
                last_ts = 0.0
        if last_ts and now - last_ts < refresh_seconds:
            continue
        eligible.append((0 if not last else 1, -visible, last_ts, identifier))
    eligible.sort()
    return [row[-1] for row in eligible[:max_items]]


def _mark_queue_batch(queue: dict, candidates: list[str], success: bool) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    items = queue.get("items") or {}
    for identifier in candidates:
        item = items.get(identifier)
        if not isinstance(item, dict):
            continue
        if success:
            item["last_deep_crawled_at"] = now
            item["retry_count"] = 0
        else:
            item["retry_count"] = int(item.get("retry_count") or 0) + 1


def _queue_pending_count(queue: dict, refresh_seconds: int) -> int:
    return len(_select_queue_candidates(queue, max_items=10**9, refresh_seconds=refresh_seconds))


def _run_detail_comment_recovery(
    cfg: dict,
    platform: str,
    candidates: list[str],
    output_dir: Path,
    stdout_log: Path,
    stderr_log: Path,
    *,
    batch_size: int | None = None,
) -> tuple[int | None, int]:
    if not candidates:
        return 0, 0
    if batch_size is None:
        batch_size = max(1, int(cfg.get("detail_comment_recovery_batch_size", 10)))
    else:
        batch_size = max(1, int(batch_size))
    batches = 0
    last_rc = 0
    for start in range(0, len(candidates), batch_size):
        batch = candidates[start:start + batch_size]
        max_comments = _effective_comment_limit(cfg)
        if platform == "toutiao":
            repo_root = Path(__file__).resolve().parents[1]
            profile_dir = Path(cfg["data_root"]) / "state" / "toutiao_browser_profile"
            cmd = [
                "uv", "run", "--project", str(cfg["media_crawler_root"]),
                "python", str(repo_root / "scripts" / "toutiao_crawler.py"),
                "--mode", "detail",
                "--specified-id", ",".join(batch),
                "--save-data-path", str(output_dir),
                "--profile-dir", str(profile_dir),
                "--get-comment", "yes",
                "--max-comments", str(max_comments or 100),
            ]
            detail_cwd = repo_root
        else:
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
            ]
            if max_comments is not None:
                cmd.extend(["--max_comments_count_singlenotes", str(max_comments)])
            detail_cwd = cfg["media_crawler_root"]
        with stdout_log.open("a", encoding="utf-8") as out, stderr_log.open("a", encoding="utf-8") as err:
            out.write(f"\n[monitor] DETAIL_COMMENT_RECOVERY batch={batches + 1} items={len(batch)}\n")
            proc = subprocess.run(cmd, cwd=detail_cwd, stdout=out, stderr=err, text=True)
        batches += 1
        last_rc = proc.returncode
        if last_rc != 0:
            break
    return last_rc, batches


def _classify_state(
    return_code: int | None,
    stdout_log: Path,
    stderr_log: Path,
    runner_error: str = "",
    *,
    content_row_count: int = 0,
    comment_row_count: int = 0,
    comments_enabled: bool = False,
) -> str:
    if runner_error:
        return "RUNNER_ERROR"

    text = _tail_text(stdout_log, stderr_log)

    verify_markers = (
        "captcha", "security verification", "manual verify", "verify_required",
        "滑块", "验证码", "安全验证", "人工验证", "weibo_verify_required",
    )
    login_markers = (
        "login required", "qrcode not found", "scan code", "扫码登录", "登录失效", "需要登录",
        "账号未登录", "bilibili_login_required",
    )
    network_markers = (
        "connecttimeout", "readtimeout", "timed out", "timeout", "err_timed_out",
        "connection reset", "connection refused", "err_connection_reset", "err_connection_refused",
        "http 502", "status 502", "http 503", "status 503", "http 504", "status 504",
        "name resolution", "dns error", "networkerror",
    )
    natural_end_markers = (
        "这里还没有内容",
        "'cards': []",
        '"cards": []',
        "cards=[]",
    )

    recovered_transport_markers = (
        "fallback to standard mode",
        "回退到标准模式",
        "continued after main navigation commit",
    )
    clean_completion_markers = (
        "crawler finished",
        "douyin crawler finished",
    )

    # A zero process exit plus valid persisted data means the collector recovered
    # successfully.  Startup/fallback warnings (for example a CDP 502 followed by
    # a healthy standard-Playwright run) must not downgrade the whole cycle to a
    # transport failure merely because the warning remains in stdout/stderr.
    if return_code == 0 and (content_row_count > 0 or comment_row_count > 0):
        if comments_enabled and content_row_count > 0 and comment_row_count == 0:
            return "SUCCESS_NO_COMMENTS"
        return "SUCCESS"

    # When no usable data was produced, explicit verification/login evidence still
    # takes precedence over generic transport errors so humans receive the correct
    # recovery instruction instead of an automatic network retry.
    if any(marker in text for marker in verify_markers):
        return "VERIFY_REQUIRED"
    if any(marker in text for marker in login_markers):
        return "LOGIN_REQUIRED"

    # A startup transport warning that was explicitly recovered (for example,
    # Douyin CDP HTTP 502 followed by a successful fallback to standard mode)
    # must not turn a clean zero-row search into NETWORK_ERROR.  When the
    # collector exits 0 and logs both the recovery and a normal completion,
    # treat the cycle as a legitimate soft-empty probe.
    if (
        return_code == 0
        and any(marker in text for marker in recovered_transport_markers)
        and any(marker in text for marker in clean_completion_markers)
    ):
        return "SOFT_EMPTY"

    if (
        ("xhs_realtime_search_timeout" in text or "toutiao_realtime_search_timeout" in text)
        and content_row_count > 0
    ):
        return "PARTIAL_SUCCESS"

    # A bounded Toutiao detail-candidate timeout after successful discovery is
    # not a platform-wide network failure. Preserve the discovered content and
    # report a partial cycle; the candidate stays retryable in the deep queue.
    if "toutiao_realtime_detail_candidate_timeout" in text and content_row_count > 0:
        return "PARTIAL_SUCCESS"

    # WB search can time out after already persisting usable JSONL.
    # Later detail/CDP output may push the marker outside _tail_text(),
    # so check the complete logs before declaring NETWORK_ERROR.
    if (
        content_row_count > 0
        and _log_line_has_markers(
            (stdout_log, stderr_log),
            "wb_realtime_search_timeout",
            "partial_jsonl_preserved=yes",
        )
    ):
        return "PARTIAL_SUCCESS"

    if any(marker in text for marker in network_markers):
        return "NETWORK_ERROR"

    if return_code not in (0, None) and any(marker in text for marker in natural_end_markers):
        return "NATURAL_END"

    if return_code == 0:
        return "SOFT_EMPTY"

    if return_code is None:
        return "RUNNER_ERROR"
    return "CRAWLER_FAILED"


def _effective_notes_limit(cfg: dict) -> int:
    configured = max(1, int(cfg.get("crawler_max_notes_count", 20)))
    if bool(cfg.get("search_until_exhausted", False)):
        return max(configured, int(cfg.get("natural_end_notes_safety_cap", 100000)))
    return configured


def _effective_comment_limit(cfg: dict) -> int | None:
    value = cfg.get("max_comments_count_singlenotes")
    if value is None and not bool(cfg.get("comments_until_exhausted", False)):
        return None
    configured = max(1, int(value or 10))
    if bool(cfg.get("comments_until_exhausted", False)):
        return max(configured, int(cfg.get("natural_end_comments_safety_cap", 100000)))
    return configured


def run_platform(cfg: dict, platform_cfg: dict, run_root: Path) -> PlatformRun:
    code = platform_cfg["code"]
    name = platform_cfg.get("name", code)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = run_root / f"{code}_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = output_dir / "stdout.log"
    stderr_log = output_dir / "stderr.log"

    monitor_comments_enabled = str(cfg.get("get_comment", "no")).lower() in {"yes", "true", "1", "y", "t"}
    realtime_mode = bool(cfg.get("realtime_mode", False))
    search_get_comment = "no" if realtime_mode else str(cfg.get("get_comment", "no"))
    search_get_sub_comment = "no" if realtime_mode else str(cfg.get("get_sub_comment", "no"))
    realtime_notes_default = 20 if code in {"bili", "wb"} else int(cfg.get("realtime_discovery_max_notes_count", 60))
    notes_limit = (
        max(1, int(cfg.get(
            f"{code}_realtime_discovery_max_notes_count",
            realtime_notes_default,
        )))
        if realtime_mode else _effective_notes_limit(cfg)
    )
    search_concurrency = max(1, int(cfg.get("max_concurrency_num", 1)))
    if realtime_mode:
        platform_search_default = 4 if code == "bili" else search_concurrency
        try:
            search_concurrency = max(1, min(
                int(cfg.get(f"{code}_realtime_search_concurrency", platform_search_default)),
                6,
            ))
        except Exception:
            search_concurrency = platform_search_default

    if code == "toutiao":
        repo_root = Path(__file__).resolve().parents[1]
        profile_dir = Path(cfg["data_root"]) / "state" / "toutiao_browser_profile"
        cmd = [
            "uv", "run", "--project", str(cfg["media_crawler_root"]),
            "python", str(repo_root / "scripts" / "toutiao_crawler.py"),
            "--mode", "search",
            "--keywords", ",".join(cfg["keywords"]),
            "--save-data-path", str(output_dir),
            "--profile-dir", str(profile_dir),
            "--max-notes", str(notes_limit),
            "--get-comment", "no",
        ]
        search_cwd = repo_root
    else:
        cmd = [
            "uv", "run", "main.py",
            "--platform", code,
            "--lt", cfg.get("login_type", "qrcode"),
            "--type", "search",
            "--keywords", ",".join(cfg["keywords"]),
            "--crawler_max_notes_count", str(notes_limit),
            "--max_concurrency_num", str(search_concurrency),
            "--get_comment", search_get_comment,
            "--get_sub_comment", search_get_sub_comment,
            "--save_data_option", cfg.get("save_data_option", "jsonl"),
            "--save_data_path", str(output_dir),
        ]
        search_cwd = cfg["media_crawler_root"]

    if not realtime_mode:
        max_comments = _effective_comment_limit(cfg)
        if max_comments is not None:
            cmd.extend(["--max_comments_count_singlenotes", str(max_comments)])

    started_dt = datetime.now()
    started = time.time()
    rc = None
    error = ""
    status = "unknown"
    recovery_candidates: list[str] = []
    recovery_batches = 0
    deep_queue_pending = 0
    try:
        search_env = None
        if realtime_mode and code in {"bili", "wb", "xhs"}:
            search_env = os.environ.copy()
            if code == "bili":
                try:
                    realtime_items_per_keyword = max(
                        1,
                        min(
                            int(cfg.get("bili_realtime_items_per_keyword", 5)),
                            20,
                        ),
                    )
                except Exception:
                    realtime_items_per_keyword = 5
                search_env["PROMOTION_WEEK_BILI_REALTIME_DISCOVERY"] = "1"
                search_env["PROMOTION_WEEK_BILI_REALTIME_ITEMS_PER_KEYWORD"] = str(
                    realtime_items_per_keyword
                )
            elif code == "wb":
                # Realtime Weibo search uses snippets only; full-text enrichment
                # remains in the historical/backfill path.
                search_env["PROMOTION_WEEK_WB_REALTIME"] = "1"
            elif code == "xhs":
                search_env["PROMOTION_WEEK_XHS_REALTIME_DISCOVERY"] = "1"
                try:
                    xhs_items_per_keyword = max(
                        1,
                        min(int(cfg.get("xhs_realtime_items_per_keyword", 5)), 10),
                    )
                except Exception:
                    xhs_items_per_keyword = 5
                search_env["PROMOTION_WEEK_XHS_REALTIME_ITEMS_PER_KEYWORD"] = str(
                    xhs_items_per_keyword
                )

        with stdout_log.open("w", encoding="utf-8") as out, stderr_log.open("w", encoding="utf-8") as err:
            search_timeout = None
            if realtime_mode and code == "wb":
                try:
                    search_timeout = max(60, min(
                        int(cfg.get("wb_realtime_search_timeout_seconds", 150)),
                        180,
                    ))
                except Exception:
                    search_timeout = 150
            elif realtime_mode and code == "xhs":
                try:
                    search_timeout = max(60, min(
                        int(cfg.get("xhs_realtime_search_timeout_seconds", 120)),
                        150,
                    ))
                except Exception:
                    search_timeout = 120
            elif realtime_mode and code == "toutiao":
                try:
                    search_timeout = max(90, min(
                        int(cfg.get("toutiao_realtime_search_timeout_seconds", 180)),
                        240,
                    ))
                except Exception:
                    search_timeout = 180
            elif realtime_mode and code == "zhihu":
                try:
                    configured_timeout = int(
                        cfg.get("zhihu_realtime_search_timeout_seconds", 150)
                    )
                    search_timeout = (
                        None
                        if configured_timeout <= 0
                        else max(30, min(configured_timeout, 1800))
                    )
                except Exception:
                    search_timeout = 150
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=search_cwd,
                    stdout=out,
                    stderr=err,
                    text=True,
                    env=search_env,
                    timeout=search_timeout,
                )
                rc = proc.returncode
                status = "ok" if rc == 0 else "failed"
            except subprocess.TimeoutExpired:
                # Realtime discovery is intentionally bounded.  subprocess.run()
                # terminates the child on timeout; any JSONL rows already flushed
                # remain usable and are ingested below.
                rc = 124
                status = "failed"
                timeout_marker = {
                    "wb": "WB_REALTIME_SEARCH_TIMEOUT",
                    "xhs": "XHS_REALTIME_SEARCH_TIMEOUT",
                    "toutiao": "TOUTIAO_REALTIME_SEARCH_TIMEOUT",
                    "zhihu": "ZHIHU_REALTIME_SEARCH_TIMEOUT",
                }.get(code, "REALTIME_SEARCH_TIMEOUT")
                err.write(
                    f"\n[monitor] {timeout_marker} timeout={search_timeout}s; "
                    "partial_jsonl_preserved=yes\n"
                )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        status = "error"

    content_files = find_content_jsonl(output_dir)
    comment_files = find_comment_jsonl(output_dir)
    content_rows = _count_jsonl_rows(content_files)
    comment_rows = _count_jsonl_rows(comment_files)

    comments_expected_this_cycle = monitor_comments_enabled

    if not error and realtime_mode and monitor_comments_enabled and content_rows > 0:
        qpath = _queue_path(cfg, code)
        queue = _load_queue(qpath)
        _update_queue_from_content(code, content_files, queue)
        refresh_seconds = max(300, int(cfg.get("realtime_comment_refresh_seconds", 900)))
        realtime_detail_default = 1 if code == "bili" else int(cfg.get("realtime_detail_max_items_per_cycle", 12))
        max_items = max(1, int(cfg.get(
            f"{code}_realtime_detail_max_items_per_cycle",
            realtime_detail_default,
        )))
        recovery_candidates = _select_queue_candidates(queue, max_items, refresh_seconds)
        comments_expected_this_cycle = bool(recovery_candidates)
        if recovery_candidates:
            recovery_rc, recovery_batches = _run_detail_comment_recovery(
                cfg,
                code,
                recovery_candidates,
                output_dir,
                stdout_log,
                stderr_log,
                batch_size=int(cfg.get("realtime_detail_batch_size", 4)),
            )
            _mark_queue_batch(queue, recovery_candidates, recovery_rc == 0)
            if recovery_rc not in (0, None):
                rc = recovery_rc
            content_files = find_content_jsonl(output_dir)
            comment_files = find_comment_jsonl(output_dir)
            content_rows = _count_jsonl_rows(content_files)
            comment_rows = _count_jsonl_rows(comment_files)
        deep_queue_pending = _queue_pending_count(queue, refresh_seconds)
        queue["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        queue["pending_due"] = deep_queue_pending
        _save_queue(qpath, queue)

    elif (
        not error
        and monitor_comments_enabled
        and content_rows > 0
        and comment_rows == 0
        and bool(cfg.get("detail_comment_recovery", True))
    ):
        max_items = max(1, int(cfg.get("detail_comment_recovery_max_items", 30)))
        recovery_candidates = _detail_recovery_candidates(code, content_files, max_items)
        comments_expected_this_cycle = bool(recovery_candidates)
        if recovery_candidates:
            recovery_rc, recovery_batches = _run_detail_comment_recovery(
                cfg, code, recovery_candidates, output_dir, stdout_log, stderr_log
            )
            if recovery_rc not in (0, None):
                rc = recovery_rc
            content_files = find_content_jsonl(output_dir)
            comment_files = find_comment_jsonl(output_dir)
            content_rows = _count_jsonl_rows(content_files)
            comment_rows = _count_jsonl_rows(comment_files)

    state = _classify_state(
        rc,
        stdout_log,
        stderr_log,
        runner_error=error,
        content_row_count=content_rows,
        comment_row_count=comment_rows,
        comments_enabled=comments_expected_this_cycle,
    )

    if state in {"NATURAL_END", "SOFT_EMPTY"}:
        status = "ok"
    elif state in {"VERIFY_REQUIRED", "LOGIN_REQUIRED", "NETWORK_ERROR", "CRAWLER_FAILED", "RUNNER_ERROR"}:
        status = "failed"
    else:
        status = "ok"

    return PlatformRun(
        platform=code,
        platform_name=name,
        started_at=started_dt.isoformat(timespec="seconds"),
        finished_at=datetime.now().isoformat(timespec="seconds"),
        duration_seconds=round(time.time() - started, 2),
        return_code=rc,
        output_dir=str(output_dir),
        stdout_log=str(stdout_log),
        stderr_log=str(stderr_log),
        status=status,
        state=state,
        error=error,
        content_file_count=len(content_files),
        comment_file_count=len(comment_files),
        content_row_count=content_rows,
        comment_row_count=comment_rows,
        detail_recovery_candidates=len(recovery_candidates),
        detail_recovery_batches=recovery_batches,
        realtime_mode=realtime_mode,
        deep_queue_pending=deep_queue_pending,
    )


def find_content_jsonl(output_dir: Path) -> list[Path]:
    result = []
    for p in output_dir.rglob("*.jsonl"):
        low = p.name.lower()
        if "content" in low and "comment" not in low:
            result.append(p)
    return sorted(result)


def find_comment_jsonl(output_dir: Path) -> list[Path]:
    result = []
    for p in output_dir.rglob("*.jsonl"):
        low = p.name.lower()
        if "comment" in low:
            result.append(p)
    return sorted(result)


def find_ingest_jsonl(output_dir: Path, include_comments: bool = False) -> list[Path]:
    files = find_content_jsonl(output_dir)
    if include_comments:
        files.extend(find_comment_jsonl(output_dir))
    return sorted(dict.fromkeys(files))
