from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.normalizer import normalize_record


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


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


def _platform_root(cfg: dict) -> Path:
    base = Path(cfg["data_root"])
    if base.name.endswith("_ks"):
        return base
    return base.parent / f"{base.name}_ks"


def _latest_cycle(root: Path) -> Path | None:
    raw_root = root / "raw_runs"
    if not raw_root.exists():
        return None
    cycles = sorted((p for p in raw_root.iterdir() if p.is_dir()), key=lambda p: p.name)
    return cycles[-1] if cycles else None


def _first_present(row: dict, *keys):
    for key in keys:
        if key in row and row.get(key) is not None and row.get(key) != "":
            return row.get(key)
    return None


def _nested_first_present(row: dict, containers: tuple[str, ...], *keys):
    value = _first_present(row, *keys)
    if value is not None:
        return value
    for name in containers:
        nested = row.get(name)
        if isinstance(nested, dict):
            value = _first_present(nested, *keys)
            if value is not None:
                return value
    return None


def _field_presence(rows: list[dict], getter) -> tuple[int, list[str]]:
    count = 0
    samples: list[str] = []
    for row in rows:
        value = getter(row)
        if value is None:
            continue
        count += 1
        text = str(value).strip()
        if text not in samples and len(samples) < 5:
            samples.append(text)
    return count, samples


def main() -> int:
    ap = argparse.ArgumentParser(description="Strict Kuaishou public-metric live acceptance.")
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = _load(cfg_path)
    if not cfg:
        print(json.dumps({"ok": False, "error": "config_not_readable", "config": str(cfg_path)}, ensure_ascii=False, indent=2))
        return 2

    root = _platform_root(cfg)
    cycle = _latest_cycle(root)
    if cycle is None:
        print(json.dumps({"ok": False, "error": "no_raw_cycle", "data_root": str(root)}, ensure_ascii=False, indent=2))
        return 2

    files = sorted(cycle.rglob("*.jsonl"))
    content_files = [p for p in files if "content" in p.name.lower() and "comment" not in p.name.lower()]
    comment_files = [p for p in files if "comment" in p.name.lower()]

    content_rows: list[dict] = []
    comment_rows: list[dict] = []
    for p in content_files:
        content_rows.extend(list(_iter_jsonl(p) or []))
    for p in comment_files:
        comment_rows.extend(list(_iter_jsonl(p) or []))

    video_like_count, video_like_samples = _field_presence(
        content_rows,
        lambda r: _first_present(r, "liked_count", "like_count", "realLikeCount", "likeCount"),
    )
    video_comment_count_count, video_comment_count_samples = _field_presence(
        content_rows,
        lambda r: _first_present(r, "comment_count", "commentCount", "commentCountV2", "commentsCount"),
    )
    follower_count_count, follower_samples = _field_presence(
        content_rows,
        lambda r: _nested_first_present(
            r, ("author", "user", "user_info", "creator"),
            "follower_count", "fans_count", "fan_count", "fan", "fans",
        ),
    )
    following_count_count, following_samples = _field_presence(
        content_rows,
        lambda r: _nested_first_present(
            r, ("author", "user", "user_info", "creator"),
            "following_count", "follow_count", "follow", "following",
        ),
    )
    comment_like_count, comment_like_samples = _field_presence(
        comment_rows,
        lambda r: _first_present(r, "like_count", "liked_count", "realLikedCount", "likedCount", "likeCount", "realLikeCount"),
    )
    comment_parent_count, parent_samples = _field_presence(
        comment_rows,
        lambda r: _first_present(
            r, "parent_comment_id", "parent_id", "reply_comment_id",
            "reply_to_comment_id", "reply_to_id", "parent_rpid",
        ),
    )
    comment_root_count, root_samples = _field_presence(
        comment_rows,
        lambda r: _first_present(r, "root_comment_id", "root_id", "root_rpid"),
    )

    normalized_content = [
        normalize_record(row, source_file="acceptance_content.jsonl", platform_hint="ks")
        for row in content_rows
    ]
    normalized_content = [row for row in normalized_content if row]
    normalized_comments = [
        normalize_record(row, source_file="acceptance_comment.jsonl", platform_hint="ks")
        for row in comment_rows
    ]
    normalized_comments = [row for row in normalized_comments if row]

    normalized_video_likes = sum(1 for row in normalized_content if row.get("likes") is not None)
    normalized_video_comments = sum(1 for row in normalized_content if row.get("comments") is not None)
    normalized_followers = sum(1 for row in normalized_content if row.get("follower_count") is not None)
    normalized_following = sum(1 for row in normalized_content if row.get("following_count") is not None)
    normalized_comment_likes = sum(1 for row in normalized_comments if row.get("likes") is not None)

    missing_contract = normalize_record(
        {"platform": "ks", "video_id": "missing-contract", "title": "contract"},
        source_file="contract.jsonl",
        platform_hint="ks",
    )
    zero_contract = normalize_record(
        {
            "platform": "ks",
            "video_id": "zero-contract",
            "title": "contract",
            "realLikeCount": 0,
            "commentCount": 0,
        },
        source_file="contract.jsonl",
        platform_hint="ks",
    )
    missing_vs_zero_ok = bool(
        missing_contract
        and missing_contract.get("likes") is None
        and missing_contract.get("comments") is None
        and zero_contract
        and zero_contract.get("likes") == 0
        and zero_contract.get("comments") == 0
    )

    checks = {
        "content_rows_present": len(content_rows) > 0,
        "comment_rows_present": len(comment_rows) > 0,
        "video_like_raw_present": video_like_count > 0,
        "video_comment_count_raw_present": video_comment_count_count > 0,
        "follower_count_raw_present": follower_count_count > 0,
        "following_count_raw_present": following_count_count > 0,
        "comment_like_raw_present": comment_like_count > 0,
        "video_like_normalized_present": normalized_video_likes > 0,
        "video_comment_count_normalized_present": normalized_video_comments > 0,
        "follower_count_normalized_present": normalized_followers > 0,
        "following_count_normalized_present": normalized_following > 0,
        "comment_like_normalized_present": normalized_comment_likes > 0,
        "missing_vs_real_zero_contract": missing_vs_zero_ok,
    }
    ok = all(checks.values())

    result = {
        "ok": ok,
        "platform": "ks",
        "config": str(cfg_path),
        "data_root": str(root),
        "cycle": cycle.name,
        "counts": {
            "content_rows": len(content_rows),
            "comment_rows": len(comment_rows),
            "video_like_raw_records": video_like_count,
            "video_comment_count_raw_records": video_comment_count_count,
            "follower_count_raw_records": follower_count_count,
            "following_count_raw_records": following_count_count,
            "comment_like_raw_records": comment_like_count,
            "comment_parent_records": comment_parent_count,
            "comment_root_records": comment_root_count,
            "normalized_video_like_records": normalized_video_likes,
            "normalized_video_comment_count_records": normalized_video_comments,
            "normalized_follower_records": normalized_followers,
            "normalized_following_records": normalized_following,
            "normalized_comment_like_records": normalized_comment_likes,
        },
        "samples": {
            "video_likes": video_like_samples,
            "video_comment_counts": video_comment_count_samples,
            "followers": follower_samples,
            "following": following_samples,
            "comment_likes": comment_like_samples,
            "parent_ids": parent_samples,
            "root_ids": root_samples,
        },
        "checks": checks,
        "note": (
            "This inspector verifies that public Kuaishou counters survive the live raw JSONL "
            "and normalization paths. Share/repost/favorite are reported only when the platform "
            "payload exposes them; they are not fabricated."
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
