from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_XHS_PUBLIC_REGION_V1"


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
    old = "from tools.public_region import coarse_public_region"
    if old not in text:
        anchor = "from tools.user_hash import anonymize_user_id, mask_nickname\n"
        text = replace_once(
            text,
            anchor,
            anchor + f"from tools.public_region import coarse_public_region, public_region_probe  # {MARKER}\n",
            "xhs public-region import",
        )
    elif "public_region_probe" not in text[:2500]:
        text = text.replace(
            old + "  # PROMOTION_WEEK_PUBLIC_REGION_PATCH_V4",
            old + f", public_region_probe  # {MARKER}",
            1,
        )
        if "public_region_probe" not in text[:2500]:
            text = text.replace(old, old + ", public_region_probe", 1)
    return text


def ensure_helper(text: str) -> str:
    helper = f'''

_XHS_PUBLIC_REGION_KEYS = {{
    "ip_location", "iplocation", "ip_region", "ipregion",
    "ip_label", "region_name", "province_name",
}}


def _xhs_find_coarse_public_region(obj):
    """Return only a platform-displayed coarse region from the public payload.

    Profile free-text locations, network addresses and coordinates are ignored.
    The current XHS web note/comment payload commonly exposes ip_location
    directly.  # {MARKER}
    """
    stack = [obj]
    seen = set()
    while stack:
        value = stack.pop()
        oid = id(value)
        if oid in seen:
            continue
        seen.add(oid)
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key).lower()
                if key_text in _XHS_PUBLIC_REGION_KEYS and not isinstance(child, (dict, list, tuple)):
                    region = coarse_public_region(child)
                    if region:
                        return region
                if isinstance(child, (dict, list, tuple)):
                    stack.append(child)
        elif isinstance(value, (list, tuple)):
            stack.extend(value)
    return ""
'''
    anchor = "\n\nclass XhsStoreFactory:\n"
    if "def _xhs_find_coarse_public_region" not in text:
        return replace_once(text, anchor, helper + anchor, "xhs region helper")

    helper_start = text.find("_XHS_PUBLIC_REGION_KEYS =")
    helper_end = text.find(anchor, helper_start)
    if helper_start < 0 or helper_end < 0:
        raise RuntimeError("XHS existing region helper boundaries not found")
    return text[:helper_start] + helper.lstrip("\n") + text[helper_end:]


def patch_store(root: Path) -> None:
    path = root / "store/xhs/__init__.py"
    text = ensure_helper(ensure_imports(read(path)))

    content_logger = '    utils.logger.info(f"[store.xhs.update_xhs_note] xhs note: {local_db_item}")\n'
    content_block = (
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n'
        '        local_db_item["ip_location"] = _xhs_find_coarse_public_region(note_item)\n'
        '        local_db_item["_public_region_probe"] = public_region_probe(note_item)\n'
    )
    old_shared_content = (
        '    if config.SAVE_DATA_OPTION == "jsonl":  # PROMOTION_WEEK_PUBLIC_REGION_PATCH_V4\n'
        '        local_db_item["ip_location"] = coarse_public_region(note_item.get("ip_location") or note_item.get("ipLocation") or note_item.get("ip_label") or note_item.get("ip_region") or note_item.get("ipRegion") or note_item.get("region") or note_item.get("region_name") or user_info.get("ip_location") or user_info.get("ipLocation") or user_info.get("ip_label") or user_info.get("ip_region") or user_info.get("ipRegion") or user_info.get("region") or user_info.get("region_name"))\n'
    )
    if old_shared_content in text:
        text = text.replace(old_shared_content, content_block, 1)
    elif content_block not in text:
        text = replace_once(text, content_logger, content_block + content_logger, "xhs content region persistence")

    comment_logger = '    utils.logger.info(f"[store.xhs.update_xhs_note_comment] xhs note comment:{local_db_item}")\n'
    comment_block = (
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n'
        '        local_db_item["ip_location"] = _xhs_find_coarse_public_region(comment_item)\n'
        '        local_db_item["_public_region_probe"] = public_region_probe(comment_item)\n'
    )
    old_shared_comment = (
        '    if config.SAVE_DATA_OPTION == "jsonl":  # PROMOTION_WEEK_PUBLIC_REGION_PATCH_V4\n'
        '        local_db_item["ip_location"] = coarse_public_region(comment_item.get("ip_location") or comment_item.get("ipLocation") or comment_item.get("ip_label") or comment_item.get("ip_region") or comment_item.get("ipRegion") or comment_item.get("region") or comment_item.get("region_name") or user_info.get("ip_location") or user_info.get("ipLocation") or user_info.get("ip_label") or user_info.get("ip_region") or user_info.get("ipRegion") or user_info.get("region") or user_info.get("region_name"))\n'
    )
    if old_shared_comment in text:
        text = text.replace(old_shared_comment, comment_block, 1)
    elif comment_block not in text:
        text = replace_once(text, comment_logger, comment_block + comment_logger, "xhs comment region persistence")

    write_py(path, text)


def check(root: Path) -> dict:
    path = root / "store/xhs/__init__.py"
    result = {
        "patch_version": 1,
        "store_exists": path.exists(),
        "strict_region_helper": False,
        "content_region_persistence": False,
        "comment_region_persistence": False,
        "safe_probe": False,
        "profile_location_not_used": False,
        "ok": False,
    }
    if not path.exists():
        return result
    try:
        text = read(path)
        ast.parse(text, filename=str(path))
        result["strict_region_helper"] = "def _xhs_find_coarse_public_region" in text
        result["content_region_persistence"] = 'local_db_item["ip_location"] = _xhs_find_coarse_public_region(note_item)' in text
        result["comment_region_persistence"] = 'local_db_item["ip_location"] = _xhs_find_coarse_public_region(comment_item)' in text
        result["safe_probe"] = '"_public_region_probe"' in text and "public_region_probe" in text
        helper_slice = text[text.find("_XHS_PUBLIC_REGION_KEYS"):text.find("def _xhs_find_coarse_public_region")]
        result["profile_location_not_used"] = '"location"' not in helper_slice
        result["ok"] = all(result[k] for k in (
            "strict_region_helper",
            "content_region_persistence",
            "comment_region_persistence",
            "safe_probe",
            "profile_location_not_used",
        ))
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Persist only coarse platform-displayed XHS public regions.")
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
