from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
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

_ID_KEYS = (
    "comment_id", "parent_comment_id", "root_comment_id", "content_id",
    "note_id", "aweme_id", "photo_id", "video_id", "bvid", "tieba_id",
    "id", "rpid", "rootid",
)
_SAFE_VALUE_KEYS = (
    "ip_location", "ip_region", "ip_label", "region_name", "province",
    "comment_count", "comments_count", "comment_num", "video_comment",
    "total_comments", "reply_count", "total_replay_num", "sub_comment_count",
    "like_count", "liked_count", "share_count", "collect_count", "favorite_count",
    "publish_time", "create_time", "last_modify_ts", "comment_level",
    "content_type", "type", "source_keyword",
)
_NESTED_SCHEMA_KEYS = (
    "user", "user_info", "author", "member", "reply_control", "photo_info",
)


def _safe_name(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return text.strip("-.") or "node"


def _run_git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def _looks_like_git_auth_error(result: subprocess.CompletedProcess) -> bool:
    text = f"{result.stderr}\n{result.stdout}".lower()
    markers = (
        "authentication failed",
        "could not read username",
        "terminal prompts disabled",
        "credential",
        "repository not found",
        "permission denied",
        "403",
        "401",
    )
    return any(marker in text for marker in markers)


def _load_config(config_path: Path) -> dict:
    return json.loads(config_path.read_text(encoding="utf-8-sig"))


def _platform_roots(cfg: dict, platform: str) -> list[Path]:
    base = Path(cfg["data_root"])
    candidates = [
        base.parent / f"{base.name}_{platform}",
        base.parent / f"{base.name}_multilingual_{platform}",
    ]
    return [p for p in candidates if p.exists()]


def _stable_hash(value, namespace: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return hashlib.sha256(f"{namespace}:{text}".encode("utf-8")).hexdigest()[:20]


def _parse_iso(value: object, default_tz=None):
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        return None
    if dt.tzinfo is None and default_tz is not None:
        dt = dt.replace(tzinfo=default_tz)
    return dt


def _before_monitoring_start(row: dict, monitoring_start_time: str) -> bool:
    start = _parse_iso(monitoring_start_time)
    if start is None:
        return False
    published = _parse_iso(row.get("publish_time"), default_tz=start.tzinfo)
    return bool(published is not None and published < start)


def _reporting_excluded(row: dict) -> bool:
    # Keep this aligned with monitor.result_summary reporting exclusions.
    platform = str(row.get("platform") or "")
    record_type = str(row.get("record_type") or "")
    record_id = str(row.get("comment_id") or row.get("sample_id") or "")

    if (platform, record_type, record_id) in {
        ("bili", "comment", "314288237793"),
        ("bili", "comment", "317841315680"),
    }:
        return True

    if platform != "dy" or record_type != "video":
        return False

    signature = (
        int(row.get("likes") or 0),
        int(row.get("comments") or 0),
        int(row.get("shares") or 0),
    )
    return signature in {(46431, 50, 900), (6288, 48, 119)}


def _attitude_bucket(status: object, type_: object) -> str:
    status = str(status or "").strip()
    type_ = str(type_ or "").strip()
    if status == "normal" and type_ == "support":
        return "support"
    if status == "neutral":
        return "neutral"
    if status == "problematic":
        return "non_support"
    if status == "attention":
        return "attention"
    return "unknown"


def _tri_class_bucket(status: object) -> str:
    status = str(status or "").strip()
    if status == "normal":
        return "support"
    if status in {"attention", "neutral"}:
        return "neutral"
    if status == "problematic":
        return "non_support"
    return "unknown"


def _classified_record_fingerprints(
    roots: list[Path],
    platform: str,
    monitoring_start_time: str,
) -> list[dict]:
    """Export full-record privacy-safe fingerprints for exact cross-node dedupe.

    No raw text, raw IDs, raw URLs, real IPs or precise locations are included.
    Public coarse region labels and aggregate-safe classification fields are kept.
    """
    latest: dict[str, dict] = {}
    for root in roots:
        classified = root / "classified" / "classified_results.jsonl"
        if not classified.exists():
            continue
        try:
            with classified.open("r", encoding="utf-8-sig", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(row, dict):
                        continue
                    if _before_monitoring_start(row, monitoring_start_time) or _reporting_excluded(row):
                        continue
                    dedupe_key = str(
                        row.get("dedupe_key")
                        or f"{row.get('platform','')}:{row.get('sample_id','')}"
                    ).strip()
                    if not dedupe_key:
                        continue
                    record_hash = _stable_hash(dedupe_key, f"{platform}:record")
                    record_type = str(row.get("record_type") or "unknown")
                    parent_id = str(row.get("parent_comment_id") or "").strip()
                    root_id = str(row.get("root_comment_id") or "").strip()
                    author_basis = str(row.get("author_id") or row.get("author") or "").strip()
                    first_seen = str(row.get("first_seen_time") or "")
                    refresh_seen = str(row.get("engagement_refresh_time") or "")
                    latest_seen = max(first_seen, refresh_seen)
                    status = str(row.get("status") or "unknown")
                    type_ = str(row.get("type") or "null")
                    safe = {
                        "record_hash": record_hash,
                        "record_type": record_type,
                        "region": str(row.get("ip_location") or "").strip(),
                        "language": str(row.get("language") or "未知"),
                        "status": status,
                        "type": type_,
                        "attitude": _attitude_bucket(status, type_),
                        "tri_class": _tri_class_bucket(status),
                        "source_type": str(row.get("source_type") or "未分类"),
                        "keyword": str(row.get("source_keyword") or "").strip(),
                        "comment_level": int(row.get("comment_level") or 0),
                        "parent_hash": _stable_hash(parent_id, f"{platform}:comment") if parent_id else "",
                        "root_hash": _stable_hash(root_id, f"{platform}:comment") if root_id else "",
                        "author_hash": _stable_hash(author_basis, f"{platform}:author") if record_type == "comment" and author_basis else "",
                        "publisher_hash": _stable_hash(author_basis, f"{platform}:publisher") if record_type != "comment" and author_basis else "",
                        "latest_seen_time": latest_seen,
                        "likes": int(row.get("likes") or 0),
                        "comments": int(row.get("comments") or 0),
                        "shares": int(row.get("shares") or 0),
                        "views": int(row.get("views") or 0),
                        "favorites": int(row.get("favorites") or 0),
                        "danmaku": int(row.get("danmaku") or 0),
                        "coins": int(row.get("coins") or 0),
                        "has_asr": bool(str(row.get("asr_text") or "").strip()),
                        "has_ocr": bool(str(row.get("ocr_text") or "").strip()),
                    }
                    latest[record_hash] = safe
        except Exception:
            continue
    return [latest[k] for k in sorted(latest)]


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _count_jsonl(path: Path) -> int:
    total = 0
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                if line.strip():
                    total += 1
    except Exception:
        return 0
    return total


def _safe_value(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value).strip()
    if len(text) > 80:
        text = text[:80]
    # Diagnostic snapshots intentionally reject values that look like raw IPs.
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", text) or re.fullmatch(r"[0-9a-fA-F:]{6,}", text):
        return ""
    return text


def _sanitize_raw_row(row: dict, platform: str) -> dict:
    """Keep schema/structure for debugging without publishing user text or raw identifiers."""
    sample = {
        "fields": sorted(str(k) for k in row.keys()),
        "field_types": {str(k): type(v).__name__ for k, v in row.items()},
        "stable_id_hashes": {},
        "safe_values": {},
        "nested_fields": {},
    }
    for key in _ID_KEYS:
        if key in row and row.get(key) not in (None, ""):
            sample["stable_id_hashes"][key] = _stable_hash(row.get(key), f"{platform}:{key}")
    for key in _SAFE_VALUE_KEYS:
        if key in row and row.get(key) not in (None, ""):
            sample["safe_values"][key] = _safe_value(row.get(key))
    for key in _NESTED_SCHEMA_KEYS:
        value = row.get(key)
        if isinstance(value, dict):
            sample["nested_fields"][key] = sorted(str(k) for k in value.keys())
    return sample


def _sample_jsonl(path: Path, platform: str, limit: int) -> list[dict]:
    rows = []
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
                    rows.append(_sanitize_raw_row(row, platform))
                if len(rows) >= limit:
                    break
    except Exception:
        pass
    return rows


def _latest_raw_diagnostics(root: Path, platform: str, sample_limit: int) -> dict:
    raw_root = root / "raw_runs"
    if not raw_root.exists():
        return {"available": False, "reason": "raw_runs_missing", "data_root": str(root)}
    cycles = sorted((p for p in raw_root.iterdir() if p.is_dir()), key=lambda p: p.name)
    if not cycles:
        return {"available": False, "reason": "no_raw_cycles", "data_root": str(root)}
    cycle = cycles[-1]
    jsonl_files = sorted(cycle.rglob("*.jsonl"))
    log_files = sorted([*cycle.rglob("stdout.log"), *cycle.rglob("stderr.log")])
    files = []
    for path in jsonl_files:
        low = path.name.lower()
        kind = "comment" if "comment" in low else ("content" if "content" in low else "other")
        try:
            stat = path.stat()
            size = stat.st_size
            modified_at = datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds")
        except Exception:
            size = 0
            modified_at = ""
        files.append({
            "kind": kind,
            "name": path.name,
            "relative_path": path.relative_to(root).as_posix(),
            "bytes": size,
            "rows": _count_jsonl(path),
            "sha256": _file_sha256(path),
            "modified_at": modified_at,
            "sanitized_schema_samples": _sample_jsonl(path, platform, sample_limit),
        })
    logs = []
    for path in log_files:
        try:
            stat = path.stat()
            logs.append({
                "name": path.name,
                "relative_path": path.relative_to(root).as_posix(),
                "bytes": stat.st_size,
                "sha256": _file_sha256(path),
            })
        except Exception:
            continue
    return {
        "available": True,
        "privacy": "schema_and_structural_diagnostics_only_no_raw_text_no_raw_user_ids_no_raw_urls_no_real_ip",
        "cycle": cycle.name,
        "data_root": str(root),
        "jsonl_files": files,
        "log_files": logs,
    }


def _build_raw_diagnostics(cfg: dict, roots: list[Path], platform: str) -> list[dict]:
    if not bool(cfg.get("github_diagnostic_samples", True)):
        return []
    limit = max(1, min(20, int(cfg.get("github_diagnostic_sample_rows_per_type", 5))))
    return [_latest_raw_diagnostics(root, platform, limit) for root in roots]

def _node_build_metadata(cfg: dict) -> dict:
    head = _run_git(["rev-parse", "HEAD"])
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    media_root = Path(str(cfg.get("media_crawler_root") or "E:\\MediaCrawler_clean"))
    dy_client = media_root / "media_platform" / "douyin" / "client.py"
    dy_core = media_root / "media_platform" / "douyin" / "core.py"
    dy_store = media_root / "store" / "douyin" / "__init__.py"

    def contains(path: Path, marker: str) -> bool:
        try:
            return marker in path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return False

    return {
        "repo_head": head.stdout.strip() if head.returncode == 0 else "",
        "repo_branch": branch.stdout.strip() if branch.returncode == 0 else "",
        "douyin_request_profile_v2": contains(
            dy_client, "PROMOTION_WEEK_DY_COMMENT_REQUEST_PROFILE_V2"
        ),
        "douyin_startup_resilience": contains(
            dy_core, "PROMOTION_WEEK_DY_STARTUP_RESILIENCE"
        ),
        "douyin_parent_root_patch": (
            contains(dy_client, "PROMOTION_WEEK_DY_COMMENT_HIERARCHY")
            or contains(dy_store, "PROMOTION_WEEK_DY_COMMENT_HIERARCHY")
        ),
        "public_region_patch_v4": contains(
            dy_store, "PROMOTION_WEEK_PUBLIC_REGION_PATCH_V4"
        ),
    }


def _parse_cycle_time(name: str):
    try:
        return datetime.strptime(name, "%Y%m%d_%H%M%S").astimezone()
    except Exception:
        return None


def _tieba_discussion_thread_stats(
    roots: list[Path],
    monitoring_start_time: str,
    result_date: str,
) -> dict:
    """Count unique Tieba discussion threads discovered during the monitoring window.

    Tieba search results can legitimately point to older threads that receive fresh
    replies during the current event.  Those thread containers are useful reporting
    units even when their original publish_time predates monitoring_start_time, so
    we count them by *discovery time* from raw_runs rather than by original post time.
    This does not alter the classified-record totals; it exposes a separate reporting
    view so daily reports can include "讨论区帖子" without mislabeling historical
    publish timestamps as new publication events.
    """
    start = None
    text = str(monitoring_start_time or "").strip()
    if text:
        try:
            start = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            start = None

    first_seen_by_id: dict[str, datetime] = {}
    source_rows = 0
    for root in roots:
        raw_root = root / "raw_runs"
        if not raw_root.exists():
            continue
        for cycle in sorted((p for p in raw_root.iterdir() if p.is_dir()), key=lambda p: p.name):
            cycle_dt = _parse_cycle_time(cycle.name)
            if cycle_dt is None:
                continue
            if start is not None:
                cmp_start = start
                if cmp_start.tzinfo is None:
                    cmp_start = cmp_start.replace(tzinfo=cycle_dt.tzinfo)
                if cycle_dt < cmp_start:
                    continue
            for path in cycle.rglob("search_contents_*.jsonl"):
                try:
                    with path.open("r", encoding="utf-8-sig", errors="replace") as fh:
                        for line in fh:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                row = json.loads(line)
                            except Exception:
                                continue
                            if not isinstance(row, dict):
                                continue
                            source_rows += 1
                            thread_id = str(
                                row.get("note_id")
                                or row.get("tieba_id")
                                or row.get("content_id")
                                or row.get("id")
                                or ""
                            ).strip()
                            if not thread_id:
                                basis = "|".join(
                                    str(row.get(k) or "").strip()
                                    for k in ("note_url", "tieba_link", "title")
                                )
                                if not basis.strip("|"):
                                    continue
                                thread_id = hashlib.sha256(
                                    f"tieba-thread:{basis}".encode("utf-8", "ignore")
                                ).hexdigest()[:24]
                            old = first_seen_by_id.get(thread_id)
                            if old is None or cycle_dt < old:
                                first_seen_by_id[thread_id] = cycle_dt
                except Exception:
                    continue

    try:
        target_day = datetime.fromisoformat(result_date).date()
    except Exception:
        target_day = None
    new_on_result_date = sum(
        1 for dt in first_seen_by_id.values()
        if target_day is not None and dt.date() == target_day
    )
    return {
        "unique_threads": len(first_seen_by_id),
        "new_threads_on_result_date": new_on_result_date,
        "source_rows_scanned": source_rows,
        "record_type": "discussion_post",
        "count_basis": "unique_tieba_threads_discovered_during_monitoring_window",
        "publish_time_note": (
            "thread original publish_time may predate monitoring_start_time; "
            "daily reporting treats these as discussion containers discovered/active during monitoring"
        ),
    }


def _resolve_result_date(cfg: dict) -> str:
    """Resolve the GitHub result partition for long-running realtime monitors.

    Realtime nodes must roll over to a new results/YYYY-MM-DD partition at local
    midnight even when an older local config still contains yesterday's
    results_date.  Explicit results_date_mode=fixed remains available for
    one-off historical exports.
    """
    today = datetime.now().astimezone().date().isoformat()
    mode = str(cfg.get("results_date_mode") or "").strip().lower()
    configured = str(cfg.get("results_date") or "").strip()

    if mode == "fixed":
        return configured or today
    if mode in {"auto", "daily", "rolling"}:
        return today

    # Backward compatibility for older local configs: realtime monitoring is
    # always a rolling daily GitHub partition unless fixed mode is explicit.
    if bool(cfg.get("realtime_mode", False)):
        return today
    return configured or today


def generate_shard(config_path: Path, platform: str, node_id: str) -> tuple[Path, dict]:
    cfg = _load_config(config_path)
    roots = _platform_roots(cfg, platform)
    monitoring_start_time = str(cfg.get("monitoring_start_time") or "")
    result_date = _resolve_result_date(cfg)
    summary = build_summary(roots, monitoring_start_time=monitoring_start_time)
    if platform == "tieba":
        discussion = _tieba_discussion_thread_stats(
            roots,
            monitoring_start_time=monitoring_start_time,
            result_date=result_date,
        )
        summary["discussion_thread_stats"] = discussion
        discussion_posts = int(discussion.get("unique_threads") or 0)
        comment_records = int((summary.get("totals") or {}).get("comment_records") or 0)
        summary["reporting_record_types"] = {
            "discussion_post": discussion_posts,
            "comment": comment_records,
        }
        summary["reporting_totals"] = {
            "unique_records": discussion_posts + comment_records,
            "published_content_records": discussion_posts,
            "comment_records": comment_records,
            "new_discussion_posts_on_result_date": int(
                discussion.get("new_threads_on_result_date") or 0
            ),
        }
    payload = {
        "schema_version": 5,
        "event_id": cfg.get("event_id"),
        "event_name": cfg.get("event_name"),
        "monitoring_start_time": monitoring_start_time,
        "results_date": result_date,
        "node_id": node_id,
        "platform": platform,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sync_target_seconds": 300,
        "node_build": _node_build_metadata(cfg),
        "data_roots": [str(p) for p in roots],
        "summary": summary,
        "record_fingerprints": _classified_record_fingerprints(
            roots,
            platform,
            monitoring_start_time,
        ),
        "raw_diagnostics": _build_raw_diagnostics(cfg, roots, platform),
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


def _abort_rebase_if_needed() -> None:
    git_dir_result = _run_git(["rev-parse", "--git-dir"])
    if git_dir_result.returncode != 0:
        return
    git_dir = Path(git_dir_result.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = ROOT / git_dir
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        _run_git(["rebase", "--abort"])


def commit_and_push(path: Path, retries: int = 5) -> dict:
    rel = path.relative_to(ROOT).as_posix()
    branch = _current_branch()
    if branch in {"", "HEAD"}:
        return {
            "ok": False,
            "stage": "detached_head",
            "error": "Git working tree is not on a branch. Run the final student update workflow before restarting sync.",
            "path": rel,
        }

    # Synchronize before creating a local result commit.  This prevents a stale
    # unpublished node-result commit from being replayed during a later rebase.
    # The generated shard remains in the working tree via --autostash.
    _abort_rebase_if_needed()
    pre_pull = _run_git(["pull", "--rebase", "--autostash", "origin", branch])
    if pre_pull.returncode != 0:
        _abort_rebase_if_needed()
        return {
            "ok": False,
            "stage": "git_precommit_pull",
            "error": pre_pull.stderr.strip() or pre_pull.stdout.strip(),
            "path": rel,
        }

    add = _run_git(["add", "--", rel])
    if add.returncode != 0:
        return {"ok": False, "stage": "git_add", "error": add.stderr.strip() or add.stdout.strip(), "path": rel}

    diff = _run_git(["diff", "--cached", "--quiet", "--", rel])
    if diff.returncode == 0:
        return {"ok": True, "changed": False, "pushed": False, "path": rel}
    if diff.returncode != 1:
        return {"ok": False, "stage": "git_diff", "error": diff.stderr.strip() or diff.stdout.strip(), "path": rel}

    before_commit = _run_git(["rev-parse", "HEAD"])
    if before_commit.returncode != 0:
        return {
            "ok": False,
            "stage": "git_rev_parse",
            "error": before_commit.stderr.strip() or before_commit.stdout.strip(),
            "path": rel,
        }
    base_head = before_commit.stdout.strip()

    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    commit = _run_git(["commit", "-m", f"chore: update node monitoring result {stamp}", "--", rel])
    if commit.returncode != 0:
        return {"ok": False, "stage": "git_commit", "error": commit.stderr.strip() or commit.stdout.strip(), "path": rel}

    def rollback_local_result_commit() -> None:
        # Rewind only the result commit created above while keeping the generated
        # shard as an ordinary working-tree change.  This avoids poisoning the
        # next sync cycle after a permission/authentication failure.
        _abort_rebase_if_needed()
        _run_git(["reset", "--mixed", base_head])

    for attempt in range(1, retries + 1):
        push = _run_git(["push", "origin", f"HEAD:{branch}"])
        if push.returncode == 0:
            return {"ok": True, "changed": True, "pushed": True, "path": rel, "attempt": attempt}

        if _looks_like_git_auth_error(push):
            rollback_local_result_commit()
            return {
                "ok": False,
                "stage": "git_push_auth",
                "attempt": attempt,
                "error": push.stderr.strip() or push.stdout.strip(),
                "path": rel,
            }

        # A different node may have advanced main after our pre-commit pull.
        # Rebase once per retry; if the same node path conflicts, abort and
        # rewind our local result commit so the next cycle can regenerate cleanly.
        pull = _run_git(["pull", "--rebase", "--autostash", "origin", branch])
        if pull.returncode != 0:
            _abort_rebase_if_needed()
            rollback_local_result_commit()
            return {
                "ok": False,
                "stage": "git_postcommit_rebase",
                "attempt": attempt,
                "error": pull.stderr.strip() or pull.stdout.strip(),
                "path": rel,
            }

        if attempt < retries:
            time.sleep(2 * attempt)

    rollback_local_result_commit()
    return {
        "ok": False,
        "stage": "git_push",
        "error": push.stderr.strip() or push.stdout.strip(),
        "path": rel,
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Publish one tester/platform aggregate shard plus privacy-safe raw-schema diagnostics "
            "to GitHub. Raw post/comment text, raw user identifiers, raw URLs and real IPs are never published."
        )
    )
    parser.add_argument("--platform", required=True, choices=PLATFORMS)
    parser.add_argument("--node-id", default=os.environ.get("MONITOR_NODE_ID") or socket.gethostname())
    parser.add_argument("--config", default=str(ROOT / "config" / "monitoring.student.windows.json"))
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=300)
    args = parser.parse_args()

    if args.interval != 300:
        raise SystemExit("--interval must be exactly 300 seconds for the promotion-week real-time monitoring task")

    config_path = Path(args.config).resolve()
    while True:
        try:
            path, payload = generate_shard(config_path, args.platform, _safe_name(args.node_id))
            summary = payload["summary"]
            totals = summary.get("totals", {})
            runtime = summary.get("runtime") or []
            last_runtime = runtime[-1] if runtime else {}
            diagnostics = payload.get("raw_diagnostics") or []
            diagnostic_files = sum(
                len(row.get("jsonl_files") or [])
                for row in diagnostics if isinstance(row, dict)
            )
            result = {
                "ok": True,
                "platform": args.platform,
                "node_id": _safe_name(args.node_id),
                "path": path.relative_to(ROOT).as_posix(),
                "generated_at": payload["generated_at"],
                "monitoring_start_time": payload["monitoring_start_time"],
                "summary_schema_version": summary.get("schema_version"),
                "unique_records": totals.get("unique_records", 0),
                "comment_records": totals.get("comment_records", 0),
                "root_comment_records": totals.get("root_comment_records", 0),
                "reply_comment_records": totals.get("reply_comment_records", 0),
                "region_records": totals.get("region_records", 0),
                "comment_region_records": totals.get("comment_region_records", 0),
                "public_publisher_accounts": totals.get("public_publisher_accounts", 0),
                "attitude": summary.get("attitude") or {},
                "tri_class": summary.get("tri_class") or {},
                "comment_attitude": summary.get("comment_attitude") or {},
                "comment_tri_class": summary.get("comment_tri_class") or {},
                "video_analysis": summary.get("video_analysis") or {},
                "raw_diagnostic_file_count": diagnostic_files,
                "last_cycle": {
                    "cycle_finished_at": last_runtime.get("cycle_finished_at"),
                    "crawler_state": last_runtime.get("crawler_state"),
                    "ingest_comments": last_runtime.get("ingest_comments"),
                    "input_file_count": last_runtime.get("input_file_count", 0),
                    "comment_input_file_count": last_runtime.get("comment_input_file_count", 0),
                    "new_records": last_runtime.get("new_records", 0),
                    "classified_records": last_runtime.get("classified_records", 0),
                },
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
