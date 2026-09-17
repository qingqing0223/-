from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_DY_COMMENT_HIERARCHY_V1"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_py(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_client(root: Path) -> None:
    path = root / "media_platform/douyin/client.py"
    text = read(path)

    root_anchor = '            comments = comments_res.get("comments", [])\n'
    if "_promotion_week_root_comment_id" not in text:
        root_block = root_anchor + (
            f'            # {MARKER}\n'
            '            for _promotion_week_root_comment in comments:\n'
            '                if not isinstance(_promotion_week_root_comment, dict):\n'
            '                    continue\n'
            '                _promotion_week_root_comment_id = str(_promotion_week_root_comment.get("cid") or "").strip()\n'
            '                if _promotion_week_root_comment_id:\n'
            '                    _promotion_week_root_comment["root_comment_id"] = _promotion_week_root_comment_id\n'
        )
        text = replace_once(text, root_anchor, root_block, "douyin root hierarchy tagging")

    sub_anchor = '                        sub_comments = sub_comments_res.get("comments", [])\n'
    if "_promotion_week_sub_comment" not in text:
        sub_block = sub_anchor + (
            f'                        # {MARKER}\n'
            '                        for _promotion_week_sub_comment in sub_comments:\n'
            '                            if not isinstance(_promotion_week_sub_comment, dict):\n'
            '                                continue\n'
            '                            _promotion_week_sub_comment["root_comment_id"] = str(comment_id or "")\n'
            '                            if not str(_promotion_week_sub_comment.get("reply_id") or "").strip().strip("0"):\n'
            '                                _promotion_week_sub_comment["reply_id"] = str(comment_id or "")\n'
        )
        text = replace_once(text, sub_anchor, sub_block, "douyin sub-comment hierarchy tagging")

    write_py(path, text)


def patch_store(root: Path) -> None:
    path = root / "store/douyin/__init__.py"
    text = read(path)
    anchor = '        "parent_comment_id": parent_comment_id,\n'
    if '"root_comment_id":' not in text:
        replacement = anchor + (
            f'        # {MARKER}\n'
            '        "root_comment_id": str(comment_item.get("root_comment_id") or (comment_id if str(parent_comment_id) in {"", "0", "None"} else parent_comment_id)),\n'
        )
        text = replace_once(text, anchor, replacement, "douyin root_comment_id persistence")
    write_py(path, text)


def check(root: Path) -> dict:
    client = root / "media_platform/douyin/client.py"
    store = root / "store/douyin/__init__.py"
    result = {
        "root": str(root),
        "client_exists": client.exists(),
        "store_exists": store.exists(),
        "root_tagging": False,
        "sub_tagging": False,
        "root_persistence": False,
        "ok": False,
    }
    if not client.exists() or not store.exists():
        return result
    try:
        client_text = read(client)
        store_text = read(store)
        ast.parse(client_text, filename=str(client))
        ast.parse(store_text, filename=str(store))
        result["root_tagging"] = '_promotion_week_root_comment["root_comment_id"]' in client_text
        result["sub_tagging"] = '_promotion_week_sub_comment["root_comment_id"]' in client_text
        result["root_persistence"] = '"root_comment_id": str(comment_item.get("root_comment_id")' in store_text
        result["ok"] = all((result["root_tagging"], result["sub_tagging"], result["root_persistence"]))
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Persist Douyin first-level/nested parent-root comment hierarchy.")
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    try:
        if not args.check:
            patch_client(root)
            patch_store(root)
        result = check(root)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
