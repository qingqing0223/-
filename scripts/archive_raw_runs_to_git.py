from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
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


def _stable_hash(value, namespace: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return hashlib.sha256(f"{namespace}:{text}".encode("utf-8")).hexdigest()[:20]


def _count_rows(path: Path) -> int:
    total = 0
    with path.open("r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            if line.strip():
                total += 1
    return total


def _iter_jsonl(path: Path):
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
        return


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
    return {"version": 2, "files": {}}


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


def _coarse_region(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    # Never copy network addresses or precise coordinate-like values into the GPT feed.
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", text):
        return ""
    if re.fullmatch(r"[0-9a-fA-F:]{6,}", text):
        return ""
    if re.search(r"\d+\.\d+\s*[,，]\s*\d+\.\d+", text):
        return ""
    return text[:40]


def _first(row: dict, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _gpt_feed_row(row: dict, platform: str, kind: str) -> dict:
    content_id = _first(row, "content_id", "video_id", "photo_id", "aweme_id", "note_id", "tieba_id", "id")
    comment_id = _first(row, "comment_id", "cid", "rpid")
    parent_id = _first(row, "parent_comment_id", "parent_id", "reply_comment_id", "reply_to_comment_id", "reply_to_id", "parent_rpid")
    root_id = _first(row, "root_comment_id", "root_id", "root_rpid")
    region = _coarse_region(_first(row, "ip_location", "ip_region", "ip_label", "region", "region_name", "province"))

    out = {
        "record_type": "comment" if kind == "comment" else "content",
        "platform": platform,
        "content_id_hash": _stable_hash(content_id, f"{platform}:content"),
        "comment_id_hash": _stable_hash(comment_id, f"{platform}:comment"),
        "parent_comment_id_hash": _stable_hash(parent_id, f"{platform}:comment"),
        "root_comment_id_hash": _stable_hash(root_id, f"{platform}:comment"),
        "nickname": str(_first(row, "nickname", "author", "user_name", "user_nickname") or "")[:120],
        "title": str(_first(row, "title", "note_title", "video_title") or "")[:1000],
        "desc": str(_first(row, "desc", "description", "aweme_desc") or "")[:3000],
        "content": str(_first(row, "content", "text", "comment_text", "message") or "")[:5000],
        "create_time": _first(row, "create_time", "publish_time", "created_at", "last_modify_ts"),
        "source_keyword": str(_first(row, "source_keyword", "keyword", "search_keyword") or "")[:300],
        "ip_location": region,
        "comment_count": _first(row, "comment_count", "comments_count", "comment_num", "video_comment", "total_comments"),
        "sub_comment_count": _first(row, "sub_comment_count", "sub_comments_count", "reply_count"),
        "like_count": _first(row, "like_count", "liked_count", "realLikeCount", "likes"),
        "view_count": _first(row, "view_count", "viewd_count", "play_count", "views"),
        "share_count": _first(row, "share_count", "shares", "shared_count"),
    }
    return {k: v for k, v in out.items() if v not in (None, "")}


def _write_latest_gpt_feed(
    data_root: Path,
    archive_repo: Path,
    node_id: str,
    platform: str,
    *,
    content_limit: int = 120,
    comment_limit: int = 600,
) -> Path | None:
    raw_root = data_root / "raw_runs"
    if not raw_root.exists():
        return None
    cycles = sorted((p for p in raw_root.iterdir() if p.is_dir()), key=lambda p: p.name)
    if not cycles:
        return None
    cycle = cycles[-1]
    jsonl_files = sorted(cycle.rglob("*.jsonl"))
    content_files = [p for p in jsonl_files if "content" in p.name.lower()]
    comment_files = [p for p in jsonl_files if "comment" in p.name.lower()]

    content_rows = []
    comment_rows = []
    source_counts = Counter()
    for path in content_files:
        source_counts[path.name] += _count_rows(path)
        for row in _iter_jsonl(path) or []:
            if len(content_rows) < content_limit:
                content_rows.append(_gpt_feed_row(row, platform, "content"))
    for path in comment_files:
        source_counts[path.name] += _count_rows(path)
        for row in _iter_jsonl(path) or []:
            if len(comment_rows) < comment_limit:
                comment_rows.append(_gpt_feed_row(row, platform, "comment"))

    payload = {
        "schema_version": 1,
        "node_id": node_id,
        "platform": platform,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_cycle": cycle.name,
        "privacy": (
            "PRIVATE access-controlled GPT feed. Contains public user-generated text and masked nicknames; "
            "raw user IDs/URLs/cookies/browser state are excluded; only platform-displayed coarse IP-location labels are allowed."
        ),
        "source_file_row_counts": dict(source_counts),
        "content_records_in_feed": len(content_rows),
        "comment_records_in_feed": len(comment_rows),
        "content_limit": content_limit,
        "comment_limit": comment_limit,
        "records": content_rows + comment_rows,
    }
    dst = archive_repo / "nodes" / node_id / platform / "latest_gpt_feed.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    gpt_feed = _write_latest_gpt_feed(
        data_root,
        archive_repo,
        node_id,
        platform,
        content_limit=max(1, int(cfg.get("private_gpt_feed_content_limit", 120))),
        comment_limit=max(1, int(cfg.get("private_gpt_feed_comment_limit", 600))),
    )

    manifest_path = archive_repo / "nodes" / node_id / platform / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "node_id": node_id,
        "platform": platform,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_data_root": str(data_root),
        "privacy": "private_access_controlled_archive; no cookies/browser profiles; coarse public IP-location only when collector persisted it",
        "file_count_total": len(known),
        "latest_gpt_feed": str(gpt_feed.relative_to(archive_repo)).replace("\\", "/") if gpt_feed else "",
        "files": list(known.values()),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    state["last_archive_at"] = manifest["updated_at"]
    state["archive_repo"] = str(archive_repo)
    _save_state(state_path, state)

    commit_created = False
    push_ok = None
    if archived or status_copy is not None or gpt_feed is not None:
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
        "latest_gpt_feed": str(gpt_feed) if gpt_feed else "",
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
