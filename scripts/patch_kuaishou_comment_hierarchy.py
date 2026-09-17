from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_KS_COMMENT_HIERARCHY_V3"
LEGACY_MARKERS = (
    "PROMOTION_WEEK_KS_COMMENT_HIERARCHY_V1",
    "PROMOTION_WEEK_KS_COMMENT_HIERARCHY_V2",
)


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


def _upgrade_markers(text: str) -> str:
    for legacy in LEGACY_MARKERS:
        text = text.replace(legacy, MARKER)
    return text


def _ensure_import(text: str) -> str:
    line = "from tools.public_region import coarse_public_region"
    if line in text:
        return text
    anchor = "from tools.user_hash import anonymize_user_id, mask_nickname\n"
    return _replace_once(
        text,
        anchor,
        anchor + f"from tools.public_region import coarse_public_region  # {MARKER}\n",
        "kuaishou public region import",
    )


def _ensure_region_helper(text: str) -> str:
    if "def _ks_find_coarse_public_region" in text:
        return _upgrade_markers(text)
    anchor = "\n\nclass KuaishouStoreFactory:\n"
    helper = f'''\n\n_KS_PROVINCES = (\n    "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门",\n    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林",\n    "黑龙江", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",\n    "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西",\n    "甘肃", "青海", "台湾",\n)\n\n\ndef _ks_find_coarse_public_region(*objects):\n    """Find only a province-level public region from Kuaishou response objects.\n\n    The REST V2 response schema can drift. We inspect only location-like fields\n    and retain only coarse province-level labels. Network addresses, coordinates\n    and arbitrary profile strings are never retained.  # {MARKER}\n    """\n    key_tokens = ("ip", "region", "province", "location", "area")\n    stack = list(objects)\n    seen = set()\n    while stack:\n        obj = stack.pop()\n        oid = id(obj)\n        if oid in seen:\n            continue\n        seen.add(oid)\n        if isinstance(obj, dict):\n            for key, value in obj.items():\n                key_text = str(key).lower()\n                if any(token in key_text for token in key_tokens) and not isinstance(value, (dict, list, tuple)):\n                    region = coarse_public_region(value)\n                    for province in _KS_PROVINCES:\n                        if province in region:\n                            return province\n                if isinstance(value, (dict, list, tuple)):\n                    stack.append(value)\n        elif isinstance(obj, (list, tuple)):\n            stack.extend(obj)\n    return ""\n'''
    return _replace_once(text, anchor, helper + anchor, "kuaishou coarse region helper")


def patch_store(root: Path) -> None:
    path = root / "store/kuaishou/__init__.py"
    text = _upgrade_markers(_read(path))
    text = _ensure_import(text)
    text = _ensure_region_helper(text)

    new_video_line = (
        f'        "comment_count": str(photo_info.get("commentCount") or photo_info.get("commentCountV2") '
        f'or photo_info.get("commentsCount") or photo_info.get("comment_count") or video_item.get("commentCount") '
        f'or video_item.get("commentCountV2") or video_item.get("commentsCount") or video_item.get("comment_count") or 0),  # {MARKER}\n'
    )
    if new_video_line not in text:
        old_video = '        "viewd_count": str(photo_info.get("viewCount")),\n'
        # If a previous version already added comment_count, normalize that line in-place.
        lines = text.splitlines(keepends=True)
        replaced = False
        for i, line in enumerate(lines):
            if '"comment_count":' in line and "photo_info" in line:
                lines[i] = new_video_line
                replaced = True
                break
        if replaced:
            text = "".join(lines)
        else:
            text = _replace_once(text, old_video, old_video + new_video_line, "kuaishou video comment_count")

    new_parent = (
        f'        "parent_comment_id": str(comment_item.get("parent_comment_id") or comment_item.get("rootCommentId") or comment_item.get("root_comment_id") or ""),  # {MARKER}\n'
    )
    if '"parent_comment_id"' not in text:
        old_comment = '        "sub_comment_count": str(comment_item.get("commentCount") or comment_item.get("subCommentCount", 0)),\n'
        new_comment = (
            old_comment
            + new_parent
            + '        "root_comment_id": str(comment_item.get("root_comment_id") or comment_item.get("rootCommentId") or comment_item.get("parent_comment_id") or ""),\n'
        )
        text = _replace_once(text, old_comment, new_comment, "kuaishou comment hierarchy")

    content_logger = (
        '    utils.logger.info(\n'
        '        f"[store.kuaishou.update_kuaishou_video] Kuaishou video id:{video_id}, title:{save_content_item.get(\'title\')}")\n'
    )
    content_fallback = (
        f'    if config.SAVE_DATA_OPTION == "jsonl" and not save_content_item.get("ip_location"):  # {MARKER}\n'
        '        save_content_item["ip_location"] = _ks_find_coarse_public_region(photo_info, video_item, user_info)\n'
    )
    if content_fallback not in text:
        text = _replace_once(text, content_logger, content_fallback + content_logger, "kuaishou content recursive coarse region")

    comment_logger = (
        '    utils.logger.info(\n'
        '        f"[store.kuaishou.update_ks_video_comment] Kuaishou video comment: {comment_id}, content: {save_comment_item.get(\'content\')}")\n'
    )
    comment_fallback = (
        f'    if config.SAVE_DATA_OPTION == "jsonl" and not save_comment_item.get("ip_location"):  # {MARKER}\n'
        '        save_comment_item["ip_location"] = _ks_find_coarse_public_region(comment_item)\n'
    )
    if comment_fallback not in text:
        text = _replace_once(text, comment_logger, comment_fallback + comment_logger, "kuaishou comment recursive coarse region")

    text = _upgrade_markers(text)
    _write(path, text)


def patch_client(root: Path) -> None:
    path = root / "media_platform/kuaishou/client.py"
    text = _upgrade_markers(_read(path))

    parent_line = '                        sub_comment["parent_comment_id"] = str(root_comment_id)'
    root_line = '                        sub_comment["root_comment_id"] = str(root_comment_id)'

    # Region-enrichment patches may insert code between `sub_comments = ...` and
    # the callback. Therefore do not depend on one exact contiguous source block.
    # Detect the behavior itself first; only insert it when absent.
    if parent_line in text and root_line in text:
        # Ensure this file carries the current marker even if an older patch had
        # already installed the behavior and another patch changed nearby text.
        if MARKER not in text:
            text = text.replace(parent_line, parent_line + f"  # {MARKER}", 1)
        _write(path, text)
        return

    callback_anchor = (
        '                if callback and sub_comments:\n'
        '                    await callback(photo_id, sub_comments)\n'
    )
    tagging = (
        f'                # Preserve the root/parent link before the store callback.  # {MARKER}\n'
        '                for sub_comment in sub_comments:\n'
        '                    if isinstance(sub_comment, dict):\n'
        '                        sub_comment["parent_comment_id"] = str(root_comment_id)\n'
        '                        sub_comment["root_comment_id"] = str(root_comment_id)\n\n'
    )
    text = _replace_once(
        text,
        callback_anchor,
        tagging + callback_anchor,
        "kuaishou sub-comment callback insertion",
    )
    _write(path, text)


def check(root: Path) -> dict:
    store = root / "store/kuaishou/__init__.py"
    client = root / "media_platform/kuaishou/client.py"
    result = {
        "patch_version": 3,
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
                and all(legacy not in text for legacy in LEGACY_MARKERS)
                and '"comment_count"' in text
                and '"parent_comment_id"' in text
                and '"root_comment_id"' in text
                and "def _ks_find_coarse_public_region" in text
                and 'photo_info.get("commentCountV2")' in text
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
    result["purpose"] = "persist_kuaishou_comment_counts_nested_parent_root_and_safe_coarse_regions"
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
    ap = argparse.ArgumentParser(description="Patch pinned MediaCrawler Kuaishou output for realtime comment discovery, nested reply integrity and coarse public regions.")
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
