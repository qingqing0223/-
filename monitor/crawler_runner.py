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
    error: str = ""

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
        error=error,
    )

def find_content_jsonl(output_dir: Path) -> list[Path]:
    result = []
    for p in output_dir.rglob("*.jsonl"):
        low = p.name.lower()
        if "content" in low and "comment" not in low:
            result.append(p)
    return sorted(result)
