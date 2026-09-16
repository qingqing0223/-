from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor.result_summary import build_summary, discover_data_roots, write_summary


def _run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo_root, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def generate(repo_root: Path, config_path: Path) -> dict:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    base_data_root = Path(cfg["data_root"])
    roots = discover_data_roots(base_data_root, include_multilingual=True)
    summary = build_summary(roots)
    paths = write_summary(repo_root, summary)
    return {"ok": True, "data_roots": [str(p) for p in roots], "summary": summary, "paths": paths}


def git_commit_and_push(repo_root: Path) -> dict:
    # Only the aggregate results directory is staged. Raw crawler files, API keys,
    # cookies and browser profiles are never added by this script.
    add = _run_git(repo_root, ["add", "--", "results"])
    if add.returncode != 0:
        return {"ok": False, "stage": "git_add", "error": add.stderr.strip() or add.stdout.strip()}

    diff = _run_git(repo_root, ["diff", "--cached", "--quiet", "--", "results"])
    if diff.returncode == 0:
        return {"ok": True, "changed": False, "pushed": False}
    if diff.returncode not in (0, 1):
        return {"ok": False, "stage": "git_diff", "error": diff.stderr.strip() or diff.stdout.strip()}

    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    commit = _run_git(repo_root, ["commit", "-m", f"chore: update monitoring summary {stamp}", "--", "results"])
    if commit.returncode != 0:
        return {"ok": False, "stage": "git_commit", "error": commit.stderr.strip() or commit.stdout.strip()}

    push = _run_git(repo_root, ["push", "origin", "HEAD"])
    if push.returncode != 0:
        return {
            "ok": False,
            "stage": "git_push",
            "committed": True,
            "error": push.stderr.strip() or push.stdout.strip(),
        }
    return {"ok": True, "changed": True, "committed": True, "pushed": True}


def run_once(repo_root: Path, config_path: Path, push: bool) -> dict:
    generated = generate(repo_root, config_path)
    result = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "generated": generated,
    }
    if push:
        result["git"] = git_commit_and_push(repo_root)
    return result


def main():
    parser = argparse.ArgumentParser(description="Generate aggregate monitoring results and optionally push them to GitHub.")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--config", default=str(ROOT / "config" / "monitoring.windows.json"))
    parser.add_argument("--push", action="store_true", help="Commit only results/ and push using the machine's existing Git credentials")
    parser.add_argument("--loop", action="store_true", help="Repeat until Ctrl+C")
    parser.add_argument("--interval", type=int, default=900, help="Loop interval in seconds; default 900 (15 minutes)")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    config_path = Path(args.config).resolve()
    if args.interval < 300:
        raise SystemExit("For GitHub hygiene, --interval must be >= 300 seconds.")

    while True:
        try:
            result = run_once(repo_root, config_path, args.push)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as exc:
            print(json.dumps({
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            }, ensure_ascii=False, indent=2))

        if not args.loop:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
