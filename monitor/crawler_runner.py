from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
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


def _tail_text(*paths: Path, max_chars: int = 16000) -> str:
    parts = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            parts.append(text[-max_chars:])
        except Exception:
            pass
    return "\n".join(parts).lower()


def _classify_state(return_code: int | None, stdout_log: Path, stderr_log: Path, runner_error: str = "") -> str:
    if runner_error:
        return "RUNNER_ERROR"
    if return_code == 0:
        return "SUCCESS"

    text = _tail_text(stdout_log, stderr_log)
    verify_markers = (
        "captcha", "security verification", "manual verify", "verify_required",
        "滑块", "验证码", "安全验证", "人工验证",
    )
    login_markers = (
        "login required", "qrcode not found", "scan code", "扫码登录", "登录失效", "需要登录",
    )
    network_markers = (
        "connecttimeout", "readtimeout", "timed out", "timeout", "err_timed_out",
        "connection reset", "connection refused", "http 502", "status 502", "network",
    )
    if any(marker in text for marker in verify_markers):
        return "VERIFY_REQUIRED"
    if any(marker in text for marker in login_markers):
        return "LOGIN_REQUIRED"
    if any(marker in text for marker in network_markers):
        return "NETWORK_ERROR"
    return "CRAWLER_FAILED"


def run_platform(cfg: dict, platform_cfg: dict, run_root: Path) -> PlatformRun:
    code = platform_cfg["code"]
    name = platform_cfg.get("name", code)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = run_root / f"{code}_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = output_dir / "stdout.log"
    stderr_log = output_dir / "stderr.log"

    cmd = [
        "uv", "run", "main.py",
        "--platform", code,
        "--lt", cfg.get("login_type", "qrcode"),
        "--type", "search",
        "--keywords", ",".join(cfg["keywords"]),
        "--crawler_max_notes_count", str(cfg.get("crawler_max_notes_count", 20)),
        "--max_concurrency_num", str(cfg.get("max_concurrency_num", 1)),
        "--get_comment", str(cfg.get("get_comment", "no")),
        "--get_sub_comment", str(cfg.get("get_sub_comment", "no")),
        "--save_data_option", cfg.get("save_data_option", "jsonl"),
        "--save_data_path", str(output_dir),
    ]

    # Keep region enrichment bounded. MediaCrawler supports limiting first-level
    # comments per post/video; only pass this option when configured so the normal
    # fast path is unchanged.
    max_comments = cfg.get("max_comments_count_singlenotes")
    if max_comments is not None:
        cmd.extend(["--max_comments_count_singlenotes", str(int(max_comments))])

    started_dt = datetime.now()
    started = time.time()
    rc = None
    error = ""
    status = "unknown"
    try:
        with stdout_log.open("w", encoding="utf-8") as out, stderr_log.open("w", encoding="utf-8") as err:
            proc = subprocess.run(cmd, cwd=cfg["media_crawler_root"], stdout=out, stderr=err, text=True)
        rc = proc.returncode
        status = "ok" if rc == 0 else "failed"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        status = "error"

    state = _classify_state(rc, stdout_log, stderr_log, runner_error=error)
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
    # Stable order and no duplicates.
    return sorted(dict.fromkeys(files))
