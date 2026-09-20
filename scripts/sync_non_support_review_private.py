from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import time

from scripts.archive_raw_runs_to_git import (
    _ensure_private_confirmation,
    _git,
    _platform_data_root,
    _read_config,
    _write_non_support_review_feed,
    _write_non_support_review_sheet,
)

PLATFORMS = {"xhs", "dy", "ks", "bili", "wb", "toutiao", "zhihu"}


def sync_once(
    platform: str,
    node_id: str,
    config: Path,
    review_repo: Path,
    *,
    push: bool,
    private_confirmed: bool,
) -> dict:
    _ensure_private_confirmation(review_repo, private_confirmed)
    cfg = _read_config(config)
    data_root = _platform_data_root(cfg, platform)

    review_feed = _write_non_support_review_feed(
        data_root,
        review_repo,
        node_id,
        platform,
        str(cfg.get("monitoring_start_time") or ""),
    )
    review_sheet, confirmed = _write_non_support_review_sheet(
        review_feed,
        review_repo,
        node_id,
        platform,
    )

    rel_root = f"nodes/{node_id}/{platform}"
    _git(review_repo, "pull", "--rebase", check=False)
    _git(review_repo, "add", "--", rel_root)
    diff = _git(review_repo, "diff", "--cached", "--quiet", check=False)

    commit_created = False
    push_ok = None
    if diff.returncode != 0:
        message = (
            f"review {platform} {node_id} "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        _git(review_repo, "commit", "-m", message)
        commit_created = True
        if push:
            first = _git(review_repo, "push", check=False)
            if first.returncode != 0:
                _git(review_repo, "pull", "--rebase", check=False)
                second = _git(review_repo, "push", check=False)
                push_ok = second.returncode == 0
                if not push_ok:
                    raise RuntimeError(
                        "review repo git push failed after retry: "
                        + (second.stderr.strip() or second.stdout.strip())
                    )
            else:
                push_ok = True

    pending_count = 0
    confirmed_count = 0
    if review_feed and review_feed.exists():
        try:
            pending_count = int(
                json.loads(review_feed.read_text(encoding="utf-8")).get(
                    "pending_non_support_count", 0
                )
            )
        except Exception:
            pass
    if confirmed and confirmed.exists():
        try:
            confirmed_count = int(
                json.loads(confirmed.read_text(encoding="utf-8")).get(
                    "confirmed_non_support_count", 0
                )
            )
        except Exception:
            pass

    return {
        "ok": True,
        "platform": platform,
        "node_id": node_id,
        "data_root": str(data_root),
        "review_repo": str(review_repo),
        "pending_non_support_count": pending_count,
        "confirmed_non_support_count": confirmed_count,
        "latest_non_support_review_queue": str(review_feed) if review_feed else "",
        "manual_review_sheet": str(review_sheet) if review_sheet else "",
        "confirmed_non_support": str(confirmed) if confirmed else "",
        "commit_created": commit_created,
        "push_enabled": push,
        "push_ok": push_ok,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Sync only model-flagged non-support review material to an "
            "access-controlled PRIVATE Git repository."
        )
    )
    ap.add_argument("--platform", required=True, choices=sorted(PLATFORMS))
    ap.add_argument("--node-id", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--review-repo", required=True)
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--private-repo-confirmed", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=300)
    args = ap.parse_args()

    if args.interval != 300:
        print("ERROR: review sync interval must be exactly 300 seconds.", flush=True)
        return 2

    config = Path(args.config).resolve()
    review_repo = Path(args.review_repo).resolve()

    while True:
        try:
            result = sync_once(
                args.platform,
                args.node_id,
                config,
                review_repo,
                push=args.push,
                private_confirmed=args.private_repo_confirmed,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "platform": args.platform,
                        "node_id": args.node_id,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if not args.loop:
                return 3

        if not args.loop:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
