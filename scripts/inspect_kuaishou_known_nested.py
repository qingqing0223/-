from __future__ import annotations

import argparse
import json
from pathlib import Path


def _iter_jsonl(path: Path):
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


def _first(row: dict, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--video-id", required=True)
    args = ap.parse_args()

    root = Path(args.data_dir).resolve()
    files = sorted(root.rglob("*.jsonl"))
    comment_files = [p for p in files if "comment" in p.name.lower()]
    content_files = [p for p in files if "content" in p.name.lower() and "comment" not in p.name.lower()]

    comments = []
    for p in comment_files:
        comments.extend(list(_iter_jsonl(p)))

    contents = []
    for p in content_files:
        contents.extend(list(_iter_jsonl(p)))

    video_id = str(args.video_id)
    comments = [
        row for row in comments
        if str(_first(row, "video_id", "photo_id", "note_id") or video_id) == video_id
    ]
    contents = [
        row for row in contents
        if str(_first(row, "video_id", "photo_id", "note_id") or "") == video_id
    ]

    nested = []
    first_level = []
    for row in comments:
        parent = str(_first(
            row,
            "parent_comment_id", "parent_id", "reply_comment_id",
            "reply_to_comment_id", "root_comment_id", "root_id"
        ) or "").strip()
        if parent and parent not in {"0", "None", "null"}:
            nested.append(row)
        else:
            first_level.append(row)

    positive_video_comment_counts = []
    for row in contents:
        value = _first(
            row, "comment_count", "commentCount", "commentCountV2",
            "commentsCount", "totalCommentCount"
        )
        if value in (None, ""):
            continue
        try:
            number = int(float(str(value)))
        except Exception:
            continue
        if number > 0:
            positive_video_comment_counts.append(number)

    parent_samples = []
    for row in nested[:5]:
        parent_samples.append({
            "comment_id": str(_first(row, "comment_id", "commentId") or ""),
            "parent_comment_id": str(_first(
                row, "parent_comment_id", "parent_id", "reply_comment_id",
                "reply_to_comment_id"
            ) or ""),
            "root_comment_id": str(_first(row, "root_comment_id", "root_id") or ""),
        })

    checks = {
        "comment_files_present": bool(comment_files),
        "comments_present": len(comments) > 0,
        "first_level_present": len(first_level) > 0,
        "nested_replies_present": len(nested) > 0,
        "nested_parent_links_present": all(
            str(_first(
                row, "parent_comment_id", "parent_id", "reply_comment_id",
                "reply_to_comment_id", "root_comment_id", "root_id"
            ) or "").strip() not in {"", "0", "None", "null"}
            for row in nested
        ) if nested else False,
        "positive_video_comment_count_present": bool(positive_video_comment_counts),
    }
    ok = all(checks.values())

    print(json.dumps({
        "ok": ok,
        "video_id": video_id,
        "data_dir": str(root),
        "content_files": [str(p) for p in content_files],
        "comment_files": [str(p) for p in comment_files],
        "counts": {
            "content_rows": len(contents),
            "comment_rows": len(comments),
            "first_level_comments": len(first_level),
            "nested_replies": len(nested),
            "positive_video_comment_count_records": len(positive_video_comment_counts),
        },
        "video_comment_count_samples": positive_video_comment_counts[:5],
        "nested_parent_samples": parent_samples,
        "checks": checks,
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
