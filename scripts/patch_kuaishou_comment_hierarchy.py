from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_KS_COMMENT_HIERARCHY_V1"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_store(root: Path) -> None:
    path = root / "store/kuaishou/__init__.py"
    text = _read(path)

    old_video = '        "viewd_count": str(photo_info.get("viewCount")),\n'
    new_video = (
        '        "viewd_count": str(photo_info.get("viewCount")),\n'
        f'        "comment_count": str(photo_info.get("commentCount") or photo_info.get("comment_count") or 0),  # {MARKER}\n'
    )
    text = _replace_once(text, old_video, new_video, "kuaishou video comment_count")

    old_comment = '        "sub_comment_count": str(comment_item.get("commentCount") or comment_item.get("subCommentCount", 0)),\n'
    new_comment = (
        '        "sub_comment_count": str(comment_item.get("commentCount") or comment_item.get("subCommentCount", 0)),\n'
        f'        "parent_comment_id": str(comment_item.get("parent_comment_id") or comment_item.get("rootCommentId") or comment_item.get("root_comment_id") or ""),  # {MARKER}\n'
        '        "root_comment_id": str(comment_item.get("root_comment_id") or comment_item.get("rootCommentId") or comment_item.get("parent_comment_id") or ""),\n'
    )
    text = _replace_once(text, old_comment, new_comment, "kuaishou comment hierarchy")
    _write(path, text)


def patch_client(root: Path) -> None:
    path = root / "media_platform/kuaishou/client.py"
    text = _read(path)
    old = (
        '                sub_comments = comments_res.get("subCommentsV2", [])\n\n'
        '                if callback and sub_comments:\n'
        '                    await callback(photo_id, sub_comments)\n'
    )
    new = (
        '                sub_comments = comments_res.get("subCommentsV2", [])\n\n'
        f'                # Preserve the root/parent link before the store callback.  # {MARKER}\n'
        '                for sub_comment in sub_comments:\n'
        '                    if isinstance(sub_comment, dict):\n'
        '                        sub_comment["parent_comment_id"] = str(root_comment_id)\n'
        '                        sub_comment["root_comment_id"] = str(root_comment_id)\n\n'
        '                if callback and sub_comments:\n'
        '                    await callback(photo_id, sub_comments)\n'
    )
    text = _replace_once(text, old, new, "kuaishou sub-comment parent tagging")
    _write(path, text)


def check(root: Path) -> dict:
    store = root / "store/kuaishou/__init__.py"
    client = root / "media_platform/kuaishou/client.py"
    result = {
        "store_exists": store.exists(),
        "client_exists": client.exists(),
        "store_ok": False,
        "client_ok": False,
    }
    if store.exists():
        text = _read(store)
        try:
            ast.parse(text, filename=str(store))
            result["store_ok"] = (
                MARKER in text
                and '"comment_count"' in text
                and '"parent_comment_id"' in text
                and '"root_comment_id"' in text
            )
        except Exception:
            pass
    if client.exists():
        text = _read(client)
        try:
            ast.parse(text, filename=str(client))
            result["client_ok"] = (
                MARKER in text
                and 'sub_comment["parent_comment_id"] = str(root_comment_id)' in text
                and 'sub_comment["root_comment_id"] = str(root_comment_id)' in text
            )
        except Exception:
            pass
    result["ok"] = bool(result["store_ok"] and result["client_ok"])
    result["purpose"] = "persist_kuaishou_comment_count_and_nested_parent_root_links"
    return result


def apply(root: Path) -> dict:
    required = [
        root / "store/kuaishou/__init__.py",
        root / "media_platform/kuaishou/client.py",
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise RuntimeError("required Kuaishou source missing: " + " | ".join(missing))
    patch_store(root)
    patch_client(root)
    return check(root)


def main() -> int:
    ap = argparse.ArgumentParser(description="Patch pinned MediaCrawler Kuaishou output for realtime comment discovery and nested reply integrity.")
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    try:
        result = check(root) if args.check else apply(root)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"root": str(root), **result}, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
