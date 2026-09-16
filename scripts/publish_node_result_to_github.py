from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor.result_summary import build_summary

PLATFORMS = (
    "xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu",
    "wechat_mp", "wechat_channels",
)


def _safe_name(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return text.strip("-.") or "node"


def _run_git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def _load_config(config_path: Path) -> dict:
    return json.loads(config_path.read_text(encoding="utf-8-sig"))


def _platform_roots(cfg: dict, platform: str) -> list[Path]:
    base = Path(cfg["data_root"])
    candidates = [
        base.parent / f"{base.name}_{platform}",
        base.parent / f"{base.name}_multilingual_{platform}",
    ]
    return [p for p in candidates if p.exists()]


def generate_shard(config_path: Path, platform: str, node_id: str) -> tuple[Path, dict]:
    cfg = _load_config(config_path)
    roots = _platform_roots(cfg, platform)
    monitoring_start_time = str(cfg.get("monitoring_start_time") or "")
    result_date = str(cfg.get("results_date") or datetime.now().astimezone().date().isoformat())
    summary = build_summary(roots, monitoring_start_time=monitoring_start_time)
    payload = {
        "schema_version": 2,
        "event_id": cfg.get("event_id"),
        "event_name": cfg.get("event_name"),
        "monitoring_start_time": monitoring_start_time,
        "results_date": result_date,
        "node_id": node_id,
        "platform": platform,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "data_roots": [str(p) for p in roots],
        "summary": summary,
    }
    out = ROOT / "results" / result_date / "nodes" / platform / f"{_safe_name(node_id)}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out, payload


def _current_branch() -> str:
    p = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or "cannot read current branch")
    return p.stdout.strip()


def commit_and_push(path: Path, retries: int = 3) -> dict:
    rel = path.relative_to(ROOT).as_posix()
    add = _run_git(["add", "--", rel])
    if add.returncode != 0:
        return {"ok": False, "stage": "git_add", "error": add.stderr.strip() or add.stdout.strip()}

    diff = _run_git(["diff", "--cached", "--quiet", "--", rel])
    if diff.returncode == 0:
        return {"ok": True, "changed": False, "pushed": False, "path": rel}
    if diff.returncode != 1:
        return {"ok": False, "stage": "git_diff", "error": diff.stderr.strip() or diff.stdout.strip()}

    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    commit = _run_git(["commit", "-m", f"chore: update node monitoring result {stamp}", "--", rel])
    if commit.returncode != 0:
        return {"ok": False, "stage": "git_commit", "error": commit.stderr.strip() or commit.stdout.strip()}

    branch = _current_branch()
    for attempt in range(1, retries + 1):
        pull = _run_git(["pull", "--rebase", "--autostash", "origin", branch])
        if pull.returncode != 0:
            return {
                "ok": False,
                "stage": "git_pull_rebase",
                "attempt": attempt,
                "error": pull.stderr.strip() or pull.stdout.strip(),
            }
        push = _run_git(["push", "origin", f"HEAD:{branch}"])
        if push.returncode == 0:
            return {"ok": True, "changed": True, "pushed": True, "path": rel, "attempt": attempt}
        if attempt < retries:
            time.sleep(2)
    return {"ok": False, "stage": "git_push", "error": push.stderr.strip() or push.stdout.strip(), "path": rel}


def main():
    parser = argparse.ArgumentParser(description="Publish one tester/platform aggregate shard to GitHub without raw content.")
    parser.add_argument("--platform", required=True, choices=PLATFORMS)
    parser.add_argument("--node-id", default=os.environ.get("MONITOR_NODE_ID") or socket.gethostname())
    parser.add_argument("--config", default=str(ROOT / "config" / "monitoring.student.windows.json"))
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=300)
    args = parser.parse_args()

    if args.interval < 300:
        raise SystemExit("--interval must be >= 300 seconds")

    config_path = Path(args.config).resolve()
    while True:
        try:
            path, payload = generate_shard(config_path, args.platform, _safe_name(args.node_id))
            result = {
                "ok": True,
                "platform": args.platform,
                "node_id": _safe_name(args.node_id),
                "path": path.relative_to(ROOT).as_posix(),
                "generated_at": payload["generated_at"],
                "monitoring_start_time": payload["monitoring_start_time"],
                "unique_records": payload["summary"].get("totals", {}).get("unique_records", 0),
            }
            if args.push:
                result["git"] = commit_and_push(path)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as exc:
            print(json.dumps({
                "ok": False,
                "platform": args.platform,
                "error": f"{type(exc).__name__}: {exc}",
                "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            }, ensure_ascii=False, indent=2))

        if not args.loop:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
