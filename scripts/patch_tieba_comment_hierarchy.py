from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_TIEBA_COMMENT_HIERARCHY_V1"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_py(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def patch_model(root: Path) -> None:
    path = root / "model/m_baidu_tieba.py"
    text = read(path)
    anchor = '    parent_comment_id: str = Field(default="", description="Parent comment ID")\n'
    if 'root_comment_id: str = Field(default="", description="Root comment ID")' not in text:
        if anchor not in text:
            raise RuntimeError("Tieba comment model parent anchor not found")
        text = text.replace(
            anchor,
            anchor + f'    root_comment_id: str = Field(default="", description="Root comment ID")  # {MARKER}\n',
            1,
        )
    write_py(path, text)


def patch_helper(root: Path) -> None:
    path = root / "media_platform/tieba/help.py"
    text = read(path)

    # API first-level comments.
    api_anchor = '''            comment = TiebaComment(
                comment_id=comment_id,
                sub_comment_count=item.get("sub_post_number") or 0,
'''
    api_new = f'''            comment = TiebaComment(
                comment_id=comment_id,
                parent_comment_id="",
                root_comment_id=comment_id,  # {MARKER}
                sub_comment_count=item.get("sub_post_number") or 0,
'''
    if api_anchor in text and 'root_comment_id=comment_id' not in text:
        text = text.replace(api_anchor, api_new, 1)

    # HTML first-level comments.
    html_anchor = '''            tieba_comment = TiebaComment(
                comment_id=str(
                    comment_content_value.get("post_id")
                    or comment_selector.xpath("./@data-pid").get(default="")
                ),
                sub_comment_count=comment_content_value.get("comment_num") or 0,
'''
    html_new = f'''            _promotion_week_tieba_comment_id = str(
                comment_content_value.get("post_id")
                or comment_selector.xpath("./@data-pid").get(default="")
            )
            tieba_comment = TiebaComment(
                comment_id=_promotion_week_tieba_comment_id,
                parent_comment_id="",
                root_comment_id=_promotion_week_tieba_comment_id,  # {MARKER}
                sub_comment_count=comment_content_value.get("comment_num") or 0,
'''
    if html_anchor in text and "_promotion_week_tieba_comment_id" not in text:
        text = text.replace(html_anchor, html_new, 1)

    # Nested comments.
    sub_anchor = '''                publish_time=self._selector_text(comment_ele, f".//span[{self._class_contains('lzl_time')}]"),
                parent_comment_id=parent_comment.comment_id,
                note_id=parent_comment.note_id, note_url=parent_comment.note_url,
'''
    sub_new = f'''                publish_time=self._selector_text(comment_ele, f".//span[{{self._class_contains('lzl_time')}}]"),
                parent_comment_id=parent_comment.comment_id,
                root_comment_id=parent_comment.root_comment_id or parent_comment.comment_id,  # {MARKER}
                note_id=parent_comment.note_id, note_url=parent_comment.note_url,
'''
    # Avoid nested f-string formatting of self expression by using direct literal replacement.
    sub_new = sub_new.replace(
        'f".//span[{self._class_contains(\'lzl_time\')}]"',
        'f".//span[{self._class_contains(\'lzl_time\')}]"',
    )
    if sub_anchor in text and "root_comment_id=parent_comment.root_comment_id" not in text:
        text = text.replace(sub_anchor, sub_new, 1)

    write_py(path, text)


def check(root: Path) -> dict:
    model = root / "model/m_baidu_tieba.py"
    helper = root / "media_platform/tieba/help.py"
    result = {
        "patch_version": 1,
        "model_exists": model.exists(),
        "helper_exists": helper.exists(),
        "root_model_field": False,
        "api_root_tagging": False,
        "html_root_tagging": False,
        "nested_parent_root": False,
        "ok": False,
    }
    if not model.exists() or not helper.exists():
        return result
    try:
        model_text = read(model)
        helper_text = read(helper)
        ast.parse(model_text, filename=str(model))
        ast.parse(helper_text, filename=str(helper))
        result["root_model_field"] = 'root_comment_id: str = Field(default="", description="Root comment ID")' in model_text
        result["api_root_tagging"] = 'parent_comment_id=""' in helper_text and 'root_comment_id=comment_id' in helper_text
        result["html_root_tagging"] = "_promotion_week_tieba_comment_id" in helper_text and 'root_comment_id=_promotion_week_tieba_comment_id' in helper_text
        result["nested_parent_root"] = (
            "parent_comment_id=parent_comment.comment_id" in helper_text
            and "root_comment_id=parent_comment.root_comment_id or parent_comment.comment_id" in helper_text
        )
        result["ok"] = all(result[k] for k in (
            "root_model_field",
            "api_root_tagging",
            "html_root_tagging",
            "nested_parent_root",
        ))
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Persist Tieba first-level/nested parent-root hierarchy.")
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    try:
        if not args.check:
            patch_model(root)
            patch_helper(root)
        result = check(root)
    except Exception as exc:
        print(json.dumps({"ok": False, "root": str(root), "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"root": str(root), **result}, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
