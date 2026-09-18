from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_WB_COMMENT_HIERARCHY_V1"


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
    path = root / "media_platform/weibo/client.py"
    text = read(path)

    root_anchor = '            comment_list: List[Dict] = comments_res.get("data", [])\n'
    if "_promotion_week_wb_root_comment" not in text:
        root_block = root_anchor + (
            f'            # {MARKER}: explicit first-level hierarchy before persistence.\n'
            '            for _promotion_week_wb_root_comment in comment_list:\n'
            '                if not isinstance(_promotion_week_wb_root_comment, dict):\n'
            '                    continue\n'
            '                _promotion_week_wb_root_id = str(_promotion_week_wb_root_comment.get("id") or "").strip()\n'
            '                if not _promotion_week_wb_root_id:\n'
            '                    continue\n'
            '                _promotion_week_wb_root_comment["parent_comment_id"] = ""\n'
            '                _promotion_week_wb_root_comment["root_comment_id"] = _promotion_week_wb_root_id\n'
        )
        text = replace_once(text, root_anchor, root_block, "weibo root hierarchy tagging")

    sub_anchor = (
        '            sub_comments = comment.get("comments")\n'
        '            if sub_comments and isinstance(sub_comments, list):\n'
    )
    if "_promotion_week_wb_sub_comment" not in text:
        sub_block = sub_anchor + (
            f'                # {MARKER}: preserve nested reply parent/root links.\n'
            '                _promotion_week_wb_parent_id = str(comment.get("id") or comment.get("root_comment_id") or "").strip()\n'
            '                for _promotion_week_wb_sub_comment in sub_comments:\n'
            '                    if not isinstance(_promotion_week_wb_sub_comment, dict):\n'
            '                        continue\n'
            '                    _promotion_week_wb_reply_parent = str(\n'
            '                        _promotion_week_wb_sub_comment.get("reply_id")\n'
            '                        or _promotion_week_wb_sub_comment.get("parent_comment_id")\n'
            '                        or _promotion_week_wb_parent_id\n'
            '                        or ""\n'
            '                    ).strip()\n'
            '                    if not _promotion_week_wb_reply_parent or _promotion_week_wb_reply_parent == str(_promotion_week_wb_sub_comment.get("id") or ""):\n'
            '                        _promotion_week_wb_reply_parent = _promotion_week_wb_parent_id\n'
            '                    _promotion_week_wb_sub_comment["parent_comment_id"] = _promotion_week_wb_reply_parent\n'
            '                    _promotion_week_wb_sub_comment["root_comment_id"] = _promotion_week_wb_parent_id\n'
        )
        text = replace_once(text, sub_anchor, sub_block, "weibo sub hierarchy tagging")

    write_py(path, text)


def patch_store(root: Path) -> None:
    path = root / "store/weibo/__init__.py"
    text = read(path)

    old_parent = '        "parent_comment_id": comment_item.get("rootid", ""),\n'
    new_parent = (
        f'        # {MARKER}: root comments have no parent; nested replies retain parent/root.\n'
        '        "parent_comment_id": str(comment_item.get("parent_comment_id") or ""),\n'
        '        "root_comment_id": str(comment_item.get("root_comment_id") or comment_id),\n'
    )
    if old_parent in text:
        text = text.replace(old_parent, new_parent, 1)
    elif '"root_comment_id":' not in text:
        raise RuntimeError("weibo store hierarchy anchor not found")

    write_py(path, text)


def check(root: Path) -> dict:
    client = root / "media_platform/weibo/client.py"
    store = root / "store/weibo/__init__.py"
    result = {
        "patch_version": 1,
        "client_exists": client.exists(),
        "store_exists": store.exists(),
        "root_tagging": False,
        "sub_tagging": False,
        "root_persistence": False,
        "root_parent_empty": False,
        "ok": False,
    }
    if not client.exists() or not store.exists():
        return result
    try:
        client_text = read(client)
        store_text = read(store)
        ast.parse(client_text, filename=str(client))
        ast.parse(store_text, filename=str(store))
        result["root_tagging"] = '_promotion_week_wb_root_comment["parent_comment_id"] = ""' in client_text
        result["sub_tagging"] = '_promotion_week_wb_sub_comment["root_comment_id"] = _promotion_week_wb_parent_id' in client_text
        result["root_persistence"] = '"root_comment_id": str(comment_item.get("root_comment_id") or comment_id)' in store_text
        result["root_parent_empty"] = '"parent_comment_id": str(comment_item.get("parent_comment_id") or "")' in store_text
        result["ok"] = all((
            result["root_tagging"],
            result["sub_tagging"],
            result["root_persistence"],
            result["root_parent_empty"],
        ))
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Persist Weibo first-level/nested parent-root comment hierarchy.")
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
        print(json.dumps({"ok": False, "root": str(root), "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"root": str(root), **result}, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
