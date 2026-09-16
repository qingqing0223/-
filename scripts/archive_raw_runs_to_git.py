from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PLATFORMS = {"xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu"}


def _read_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _platform_data_root(cfg: dict, platform: str) -> Path:
    root = Path(str(cfg["data_root"]))
    if root.name.endswith(f"_{platform}"):
        return root
    return root.parent / f"{root.name}_{platform}"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_rows(path: Path) -> int:
    total = 0
    with path.open("r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            if line.strip():
                total += 1
    return total


def _state_path(data_root: Path, node_id: str, platform: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in node_id)
    return data_root / "state" / f"private_raw_archive_{safe}_{platform}.json"


def _load_state(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    return {"version": 1, "files": {}}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _gzip_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("rb") as fin, dst.open("wb") as raw_out:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_out, compresslevel=6, mtime=0) as fout:
            shutil.copyfileobj(fin, fout)


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def _ensure_private_confirmation(repo: Path, confirmed: bool) -> None:
    if not confirmed:
        raise RuntimeError(
            "Raw post/comment JSONL can contain user-generated text. Refusing to archive until "
            "--private-repo-confirmed is supplied for an access-controlled private Git repository."
        )
    if not (repo / ".git").exists():
        raise RuntimeError(f"archive repo is not a Git working tree: {repo}")


def _copy_latest_status(data_root: Path, archive_repo: Path, node_id: str, platform: str) -> Path | None:
    src = data_root / "status" / "latest_status.json"
    if not src.exists():
        return None
    dst = archive_repo / "nodes" / node_id / platform / "latest_status.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def archive_once(platform: str, node_id: str, config: Path, archive_repo: Path, push: bool, private_confirmed: bool) -> dict:
    _ensure_private_confirmation(archive_repo, private_confirmed)
    cfg = _read_config(config)
    data_root = _platform_data_root(cfg, platform)
    raw_root = data_root / "raw_runs"
    state_path = _state_path(data_root, node_id, platform)
    state = _load_state(state_path)
    known = state.setdefault("files", {})

    archived = []
    if raw_root.exists():
        for src in sorted(raw_root.rglob("*.jsonl")):
            rel = src.relative_to(raw_root)
            stat = src.stat()
            key = str(rel).replace("\\", "/")
            fingerprint = f"{stat.st_size}:{stat.st_mtime_ns}"
            if known.get(key, {}).get("fingerprint") == fingerprint:
                continue

            digest = _sha256(src)
            rows = _count_rows(src)
            cycle = rel.parts[0] if rel.parts else "unknown_cycle"
            date_key = cycle[:8] if len(cycle) >= 8 and cycle[:8].isdigit() else datetime.now().strftime("%Y%m%d")
            dst = archive_repo / "nodes" / node_id / platform / date_key / rel.parent / f"{src.name}.gz"
            _gzip_copy(src, dst)
            record = {
                "source_relative_path": key,
                "archive_relative_path": str(dst.relative_to(archive_repo)).replace("\\", "/"),
                "sha256_uncompressed": digest,
                "row_count": rows,
                "size_bytes_uncompressed": stat.st_size,
                "archived_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            known[key] = {"fingerprint": fingerprint, **record}
            archived.append(str(dst))

    status_copy = _copy_latest_status(data_root, archive_repo, node_id, platform)

    manifest_path = archive_repo / "nodes" / node_id / platform / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "node_id": node_id,
        "platform": platform,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_data_root": str(data_root),
        "privacy": "private_access_controlled_archive; no cookies/browser profiles; coarse public IP-location only when collector persisted it",
        "file_count_total": len(known),
        "files": list(known.values()),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    state["last_archive_at"] = manifest["updated_at"]
    state["archive_repo"] = str(archive_repo)
    _save_state(state_path, state)

    commit_created = False
    push_ok = None
    if archived or status_copy is not None:
        _git(archive_repo, "pull", "--rebase", check=False)
        _git(archive_repo, "add", "--", f"nodes/{node_id}/{platform}")
        diff = _git(archive_repo, "diff", "--cached", "--quiet", check=False)
        if diff.returncode != 0:
            message = f"archive {platform} {node_id} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            _git(archive_repo, "commit", "-m", message)
            commit_created = True
            if push:
                first = _git(archive_repo, "push", check=False)
                if first.returncode != 0:
                    _git(archive_repo, "pull", "--rebase", check=False)
                    second = _git(archive_repo, "push", check=False)
                    push_ok = second.returncode == 0
                    if not push_ok:
                        raise RuntimeError(f"git push failed after retry: {second.stderr.strip()}")
                else:
                    push_ok = True

    return {
        "platform": platform,
        "node_id": node_id,
        "data_root": str(data_root),
        "archive_repo": str(archive_repo),
        "new_or_changed_jsonl": len(archived),
        "manifest": str(manifest_path),
        "commit_created": commit_created,
        "push_enabled": push,
        "push_ok": push_ok,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Archive full MediaCrawler JSONL to an access-controlled private Git repo.")
    ap.add_argument("--platform", required=True, choices=sorted(PLATFORMS))
    ap.add_argument("--node-id", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--archive-repo", required=True)
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--private-repo-confirmed", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=300)
    args = ap.parse_args()

    if args.interval != 300:
        print("ERROR: raw archive sync interval must be exactly 300 seconds for this monitoring task.", file=sys.stderr)
        return 2

    config = Path(args.config).resolve()
    archive_repo = Path(args.archive_repo).resolve()

    while True:
        try:
            result = archive_once(
                args.platform,
                args.node_id,
                config,
                archive_repo,
                push=args.push,
                private_confirmed=args.private_repo_confirmed,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        except Exception as exc:
            print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), flush=True)
            if not args.loop:
                return 3
        if not args.loop:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
