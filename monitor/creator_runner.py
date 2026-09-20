from __future__ import annotations

from datetime import datetime
from pathlib import Path
import subprocess
import time

from .crawler_runner import PlatformRun, _classify_state


def run_creator_platform(cfg: dict, platform: str, platform_name: str, creator_ids: list[str], run_root: Path) -> PlatformRun:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = run_root / f"{platform}_creator_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = output_dir / "stdout.log"
    stderr_log = output_dir / "stderr.log"

    creator_ids = [str(x).strip() for x in creator_ids if str(x).strip()]
    if not creator_ids:
        raise ValueError("creator_ids is empty")

    if platform == "toutiao":
        repo_root = Path(__file__).resolve().parents[1]
        profile_dir = Path(cfg["data_root"]) / "state" / "toutiao_browser_profile"
        cmd = [
            "uv", "run", "--project", str(cfg["media_crawler_root"]),
            "python", str(repo_root / "scripts" / "toutiao_crawler.py"),
            "--mode", "creator",
            "--creator-id", ",".join(creator_ids),
            "--save-data-path", str(output_dir),
            "--profile-dir", str(profile_dir),
            "--max-notes", str(cfg.get("crawler_max_notes_count", 20)),
            "--get-comment", "no",
        ]
        cwd = repo_root
    else:
        cmd = [
            "uv", "run", "main.py",
            "--platform", platform,
            "--lt", cfg.get("login_type", "qrcode"),
            "--type", "creator",
            "--creator_id", ",".join(creator_ids),
            "--crawler_max_notes_count", str(cfg.get("crawler_max_notes_count", 20)),
            "--max_concurrency_num", str(cfg.get("max_concurrency_num", 1)),
            "--get_comment", str(cfg.get("get_comment", "no")),
            "--get_sub_comment", str(cfg.get("get_sub_comment", "no")),
            "--save_data_option", cfg.get("save_data_option", "jsonl"),
            "--save_data_path", str(output_dir),
        ]
        cwd = cfg["media_crawler_root"]

    started_dt = datetime.now()
    started = time.time()
    rc = None
    error = ""
    status = "unknown"
    try:
        with stdout_log.open("w", encoding="utf-8") as out, stderr_log.open("w", encoding="utf-8") as err:
            proc = subprocess.run(cmd, cwd=cwd, stdout=out, stderr=err, text=True)
        rc = proc.returncode
        status = "ok" if rc == 0 else "failed"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        status = "error"

    return PlatformRun(
        platform=platform,
        platform_name=platform_name,
        started_at=started_dt.isoformat(timespec="seconds"),
        finished_at=datetime.now().isoformat(timespec="seconds"),
        duration_seconds=round(time.time() - started, 2),
        return_code=rc,
        output_dir=str(output_dir),
        stdout_log=str(stdout_log),
        stderr_log=str(stderr_log),
        status=status,
        state=_classify_state(rc, stdout_log, stderr_log, runner_error=error),
        error=error,
    )
