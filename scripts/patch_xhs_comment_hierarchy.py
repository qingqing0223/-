from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_XHS_COMMENT_HIERARCHY_V1"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_py(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def patch_client(root: Path) -> None:
    path = root / "media_platform/xhs/client.py"
    text = read(path)

    root_anchor = '''            comments = comments_res["comments"]
            if len(result) + len(comments) > max_count:
'''
    root_block = f'''            comments = comments_res["comments"]
            # {MARKER}: explicit root hierarchy before persistence.
            for _promotion_week_xhs_root in comments:
                if not isinstance(_promotion_week_xhs_root, dict):
                    continue
                _promotion_week_xhs_root_id = str(_promotion_week_xhs_root.get("id") or "").strip()
                if not _promotion_week_xhs_root_id:
                    continue
                _promotion_week_xhs_root["parent_comment_id"] = ""
                _promotion_week_xhs_root["root_comment_id"] = _promotion_week_xhs_root_id
            if len(result) + len(comments) > max_count:
'''
    if root_anchor in text and "_promotion_week_xhs_root" not in text:
        text = text.replace(root_anchor, root_block, 1)

    embedded_anchor = '''                sub_comments = comment.get("sub_comments")
                if sub_comments and callback:
                    await callback(note_id, sub_comments)
'''
    embedded_block = f'''                sub_comments = comment.get("sub_comments")
                if sub_comments:
                    for _promotion_week_xhs_sub in sub_comments:
                        if not isinstance(_promotion_week_xhs_sub, dict):
                            continue
                        _promotion_week_xhs_target = _promotion_week_xhs_sub.get("target_comment") or {{}}
                        _promotion_week_xhs_parent = str(
                            _promotion_week_xhs_target.get("id")
                            or _promotion_week_xhs_sub.get("parent_comment_id")
                            or root_comment_id
                            or ""
                        ).strip()
                        if not _promotion_week_xhs_parent or _promotion_week_xhs_parent == str(_promotion_week_xhs_sub.get("id") or ""):
                            _promotion_week_xhs_parent = str(root_comment_id or "")
                        _promotion_week_xhs_sub["parent_comment_id"] = _promotion_week_xhs_parent
                        _promotion_week_xhs_sub["root_comment_id"] = str(root_comment_id or "")
                if sub_comments and callback:
                    await callback(note_id, sub_comments)
'''
    # root_comment_id is assigned a few lines below in upstream, so move its assignment
    # before embedded tagging when needed.
    if embedded_anchor in text and "_promotion_week_xhs_sub" not in text:
        before = '''                note_id = comment.get("note_id")
                sub_comments = comment.get("sub_comments")
'''
        after = '''                note_id = comment.get("note_id")
                root_comment_id = comment.get("id")
                sub_comments = comment.get("sub_comments")
'''
        if before in text:
            text = text.replace(before, after, 1)
        text = text.replace(embedded_anchor, embedded_block, 1)
        text = text.replace(
            '''                root_comment_id = comment.get("id")
                sub_comment_cursor = comment.get("sub_comment_cursor")
''',
            '''                sub_comment_cursor = comment.get("sub_comment_cursor")
''',
            1,
        )

    paged_anchor = '''                        comments = comments_res["comments"]
                        if callback:
                            await callback(note_id, comments)
'''
    paged_block = f'''                        comments = comments_res["comments"]
                        for _promotion_week_xhs_paged_sub in comments:
                            if not isinstance(_promotion_week_xhs_paged_sub, dict):
                                continue
                            _promotion_week_xhs_target = _promotion_week_xhs_paged_sub.get("target_comment") or {{}}
                            _promotion_week_xhs_parent = str(
                                _promotion_week_xhs_target.get("id")
                                or _promotion_week_xhs_paged_sub.get("parent_comment_id")
                                or root_comment_id
                                or ""
                            ).strip()
                            if not _promotion_week_xhs_parent or _promotion_week_xhs_parent == str(_promotion_week_xhs_paged_sub.get("id") or ""):
                                _promotion_week_xhs_parent = str(root_comment_id or "")
                            _promotion_week_xhs_paged_sub["parent_comment_id"] = _promotion_week_xhs_parent
                            _promotion_week_xhs_paged_sub["root_comment_id"] = str(root_comment_id or "")
                        if callback:
                            await callback(note_id, comments)
'''
    if paged_anchor in text and "_promotion_week_xhs_paged_sub" not in text:
        text = text.replace(paged_anchor, paged_block, 1)

    write_py(path, text)


def patch_store(root: Path) -> None:
    path = root / "store/xhs/__init__.py"
    text = read(path)

    old_parent = '        "parent_comment_id": target_comment.get("id", ""),  # Parent comment ID\n'
    new_parent = (
        f'        # {MARKER}: first-level comments have empty parent; nested replies retain direct parent/root.\n'
        '        "parent_comment_id": str(comment_item.get("parent_comment_id") or target_comment.get("id") or ""),\n'
        '        "root_comment_id": str(comment_item.get("root_comment_id") or comment_id),\n'
    )
    if old_parent in text:
        text = text.replace(old_parent, new_parent, 1)
    elif '"root_comment_id":' not in text:
        raise RuntimeError("XHS store hierarchy anchor not found")

    write_py(path, text)


def check(root: Path) -> dict:
    client = root / "media_platform/xhs/client.py"
    store = root / "store/xhs/__init__.py"
    result = {
        "patch_version": 1,
        "client_exists": client.exists(),
        "store_exists": store.exists(),
        "root_tagging": False,
        "embedded_sub_tagging": False,
        "paged_sub_tagging": False,
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
        result["root_tagging"] = '_promotion_week_xhs_root["parent_comment_id"] = ""' in client_text
        result["embedded_sub_tagging"] = '_promotion_week_xhs_sub["root_comment_id"]' in client_text
        result["paged_sub_tagging"] = '_promotion_week_xhs_paged_sub["root_comment_id"]' in client_text
        result["root_persistence"] = '"root_comment_id": str(comment_item.get("root_comment_id") or comment_id)' in store_text
        result["root_parent_empty"] = '"parent_comment_id": str(comment_item.get("parent_comment_id") or target_comment.get("id") or "")' in store_text
        result["ok"] = all(result[k] for k in (
            "root_tagging",
            "embedded_sub_tagging",
            "paged_sub_tagging",
            "root_persistence",
            "root_parent_empty",
        ))
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Persist XHS first-level/nested parent-root hierarchy.")
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
