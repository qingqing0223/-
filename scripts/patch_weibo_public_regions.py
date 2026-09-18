from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_WB_PUBLIC_REGION_V2"

PROVINCES = (
    "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门",
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林",
    "黑龙江", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
    "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西",
    "甘肃", "青海", "台湾",
)


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


def ensure_imports(text: str) -> str:
    if "\nimport config\n" not in text:
        text = replace_once(text, "import re\n", "import re\nimport config\n", "weibo import config")
    old = "from tools.public_region import coarse_public_region"
    if old not in text:
        anchor = "from tools.user_hash import anonymize_user_id, mask_nickname\n"
        text = replace_once(
            text,
            anchor,
            anchor + f"from tools.public_region import coarse_public_region, public_region_probe  # {MARKER}\n",
            "weibo public region import",
        )
    elif "public_region_probe" not in text[:2000]:
        text = text.replace(
            old + "  # PROMOTION_WEEK_PUBLIC_REGION_PATCH_V4",
            old + f", public_region_probe  # {MARKER}",
            1,
        )
        if "public_region_probe" not in text[:2000]:
            text = text.replace(old, old + ", public_region_probe", 1)
    return text


def ensure_helper(text: str) -> str:
    if "def _wb_find_coarse_public_region" in text:
        return text
    anchor = "\n\nclass WeibostoreFactory:\n"
    helper = f"""\n\n_WB_PROVINCES = {PROVINCES!r}\n_WB_PUBLIC_REGION_KEYS = {{\n    "ip_location", "ip_region", "ip_label", "region_name", "province_name",\n}}\n\n\ndef _wb_find_coarse_public_region(*objects):\n    \"\"\"Find only a province-level platform-displayed region label.\n\n    User profile location fields, network addresses and coordinates are ignored.\n    Only explicitly region-like response fields are inspected.  # {MARKER}\n    \"\"\"\n    stack = list(objects)\n    seen = set()\n    while stack:\n        obj = stack.pop()\n        oid = id(obj)\n        if oid in seen:\n            continue\n        seen.add(oid)\n        if isinstance(obj, dict):\n            for key, value in obj.items():\n                key_text = str(key).lower()\n                if key_text in _WB_PUBLIC_REGION_KEYS and not isinstance(value, (dict, list, tuple)):\n                    region = coarse_public_region(value)\n                    for province in _WB_PROVINCES:\n                        if province in region:\n                            return province\n                if isinstance(value, (dict, list, tuple)):\n                    stack.append(value)\n        elif isinstance(obj, (list, tuple)):\n            stack.extend(obj)\n    return ""\n"""
    return replace_once(text, anchor, helper + anchor, "weibo region helper")


def patch_store(root: Path) -> None:
    path = root / "store/weibo/__init__.py"
    text = ensure_helper(ensure_imports(read(path)))

    content_logger = '    utils.logger.info(f"[store.weibo.update_weibo_note] weibo note id:{note_id}, title:{save_content_item.get(\'content\')[:24]} ...")\n'
    content_block = (
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n'
        '        save_content_item["ip_location"] = _wb_find_coarse_public_region(mblog)\n'
        '        save_content_item["_public_region_probe"] = public_region_probe(mblog)\n'
    )
    old_shared_content = (
        '    if config.SAVE_DATA_OPTION == "jsonl":  # PROMOTION_WEEK_PUBLIC_REGION_PATCH_V4\n'
        '        save_content_item["ip_location"] = coarse_public_region(mblog.get("ip_location") or mblog.get("region_name") or mblog.get("ip_region") or user_info.get("ip_location") or user_info.get("region_name") or user_info.get("ip_region"))\n'
    )
    if old_shared_content in text:
        text = text.replace(old_shared_content, content_block, 1)
    elif content_block not in text:
        text = replace_once(text, content_logger, content_block + content_logger, "weibo content region persistence")

    comment_logger = '    utils.logger.info(f"[store.weibo.update_weibo_note_comment] Weibo note comment: {comment_id}, content: {save_comment_item.get(\'content\', \'\')[:24]} ...")\n'
    comment_block = (
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n'
        '        save_comment_item["ip_location"] = _wb_find_coarse_public_region(comment_item)\n'
        '        save_comment_item["_public_region_probe"] = public_region_probe(comment_item)\n'
    )
    old_shared_comment = (
        '    if config.SAVE_DATA_OPTION == "jsonl":  # PROMOTION_WEEK_PUBLIC_REGION_PATCH_V4\n'
        '        save_comment_item["ip_location"] = coarse_public_region(comment_item.get("ip_location") or comment_item.get("region_name") or comment_item.get("ip_region") or user_info.get("ip_location") or user_info.get("region_name") or user_info.get("ip_region"))\n'
    )
    if old_shared_comment in text:
        text = text.replace(old_shared_comment, comment_block, 1)
    elif comment_block not in text:
        text = replace_once(text, comment_logger, comment_block + comment_logger, "weibo comment region persistence")

    write_py(path, text)


def check(root: Path) -> dict:
    path = root / "store/weibo/__init__.py"
    result = {
        "patch_version": 2,
        "store_exists": path.exists(),
        "strict_region_helper": False,
        "content_region_persistence": False,
        "comment_region_persistence": False,
        "safe_probe": False,
        "profile_location_not_used": False,
        "comment_source_region_support": False,
        "ok": False,
    }
    if not path.exists():
        return result
    try:
        text = read(path)
        ast.parse(text, filename=str(path))
        result["strict_region_helper"] = "def _wb_find_coarse_public_region" in text
        result["content_region_persistence"] = 'save_content_item["ip_location"] = _wb_find_coarse_public_region(mblog)' in text
        result["comment_region_persistence"] = 'save_comment_item["ip_location"] = _wb_find_coarse_public_region(comment_item)' in text
        result["safe_probe"] = '"_public_region_probe"' in text and "public_region_probe" in text
        helper_slice = text[text.find("_WB_PUBLIC_REGION_KEYS"):text.find("def _wb_find_coarse_public_region")]
        result["profile_location_not_used"] = '"location"' not in helper_slice
        result["comment_source_region_support"] = (
            '_WB_PUBLIC_SOURCE_KEYS = {"source"}' in text
            and 'text.startswith("来自")' in text
        )
        result["ok"] = all((
            result["strict_region_helper"],
            result["content_region_persistence"],
            result["comment_region_persistence"],
            result["safe_probe"],
            result["profile_location_not_used"],
            result["comment_source_region_support"],
        ))
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Persist only coarse platform-displayed Weibo public regions.")
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    try:
        if not args.check:
            patch_store(root)
        result = check(root)
    except Exception as exc:
        print(json.dumps({"ok": False, "root": str(root), "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"root": str(root), **result}, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
