from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_KS_COMMENT_REGION_RESTORE_V2"
LEGACY_MARKER = "PROMOTION_WEEK_KS_COMMENT_REGION_RESTORE_V1"


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
    path = root / "media_platform/kuaishou/client.py"
    text = read(path)
    text = text.replace(LEGACY_MARKER, MARKER)

    if "from tools.public_region import coarse_public_region" not in text:
        text = replace_once(
            text,
            "from tools import utils\n",
            "from tools import utils\nfrom tools.public_region import coarse_public_region  # " + MARKER + "\n",
            "kuaishou comment-region import",
        )

    if "def _ks_enrich_comment_regions" not in text:
        anchor = "\n\nclass KuaiShouClient"
        helper = '''\n\n_KS_COMMENT_REGION_KEYS = (\n    "authorArea", "author_area", "author_area_name", "authorRegion", "author_region",\n    "ip_location", "ipLocation", "ip_region", "ipRegion", "province", "province_name",\n    "region", "region_name", "location", "area",\n)\n\n\ndef _ks_direct_public_region(obj):\n    if not isinstance(obj, dict):\n        return ""\n    for key in _KS_COMMENT_REGION_KEYS:\n        value = obj.get(key)\n        if value not in (None, "") and not isinstance(value, (dict, list, tuple)):\n            region = coarse_public_region(value)\n            if region:\n                return region\n    for nested_key in ("author", "user", "userInfo", "user_info"):\n        nested = obj.get(nested_key)\n        if isinstance(nested, dict):\n            region = _ks_direct_public_region(nested)\n            if region:\n                return region\n    return ""\n\n\ndef _ks_comment_id(obj):\n    if not isinstance(obj, dict):\n        return ""\n    return str(obj.get("comment_id") or obj.get("commentId") or "").strip()\n\n\ndef _ks_author_id(obj):\n    if not isinstance(obj, dict):\n        return ""\n    return str(obj.get("author_id") or obj.get("authorId") or obj.get("user_id") or obj.get("userId") or "").strip()\n\n\ndef _ks_enrich_comment_regions(response, comments):\n    """Restore Kuaishou's platform-displayed coarse comment region before storage.\n\n    Kuaishou web responses have used authorArea and several sibling/nested layouts.\n    We only retain coarse labels accepted by coarse_public_region; real IP addresses\n    and precise locations are never persisted.\n    """\n    by_comment = {}\n    by_author = {}\n    generic_by_id = {}\n    stack = [response]\n    seen = set()\n\n    while stack:\n        obj = stack.pop()\n        oid = id(obj)\n        if oid in seen:\n            continue\n        seen.add(oid)\n        if isinstance(obj, dict):\n            region = _ks_direct_public_region(obj)\n            if region:\n                cid = _ks_comment_id(obj)\n                aid = _ks_author_id(obj)\n                if cid:\n                    by_comment[cid] = region\n                if aid:\n                    by_author[aid] = region\n                generic_id = str(obj.get("id") or "").strip()\n                if generic_id and any(k in obj for k in ("name", "user_name", "author_name", "headurl", "avatar")):\n                    generic_by_id[generic_id] = region\n            for key, value in obj.items():\n                key_low = str(key).lower()\n                if any(token in key_low for token in ("area", "region", "province", "location")) and isinstance(value, dict):\n                    for raw_id, raw_region in value.items():\n                        region2 = coarse_public_region(raw_region)\n                        if region2:\n                            generic_by_id[str(raw_id)] = region2\n                if isinstance(value, (dict, list, tuple)):\n                    stack.append(value)\n        elif isinstance(obj, (list, tuple)):\n            stack.extend(obj)\n\n    enriched = 0\n    for comment in comments or []:\n        if not isinstance(comment, dict):\n            continue\n        region = _ks_direct_public_region(comment)\n        if not region:\n            cid = _ks_comment_id(comment)\n            aid = _ks_author_id(comment)\n            region = by_comment.get(cid, "") or by_author.get(aid, "") or generic_by_id.get(aid, "")\n        if region:\n            comment["ip_location"] = region\n            comment.setdefault("authorArea", region)\n            enriched += 1\n    return enriched\n'''
        text = replace_once(text, anchor, helper + anchor, "kuaishou comment-region helper")

    if "def _ks_comment_region_debug" not in text:
        anchor = "\n\nclass KuaiShouClient"
        debug_helper = '''\n\ndef _ks_comment_region_debug(response, comments, label):\n    """Log only schema/key names when public-region enrichment returns zero.\n\n    No comment text, raw network IP, coordinate or precise location value is logged.\n    """\n    first_keys = []\n    if comments and isinstance(comments[0], dict):\n        first_keys = sorted(str(k) for k in comments[0].keys())\n    regionish_paths = set()\n    stack = [("response", response, 0)]\n    seen = set()\n    while stack:\n        prefix, obj, depth = stack.pop()\n        if depth > 5:\n            continue\n        oid = id(obj)\n        if oid in seen:\n            continue\n        seen.add(oid)\n        if isinstance(obj, dict):\n            for key, value in obj.items():\n                key_text = str(key)\n                path = f"{prefix}.{key_text}"\n                low = key_text.lower()\n                if any(token in low for token in ("area", "region", "province", "location", "ip")):\n                    regionish_paths.add(path)\n                if isinstance(value, (dict, list, tuple)):\n                    stack.append((path, value, depth + 1))\n        elif isinstance(obj, (list, tuple)):\n            for item in obj[:20]:\n                if isinstance(item, (dict, list, tuple)):\n                    stack.append((prefix + "[]", item, depth + 1))\n    utils.logger.info(\n        f"[KS_COMMENT_REGION_DEBUG] label={label} comments={len(comments or [])} "\n        f"first_comment_keys={first_keys} regionish_paths={sorted(regionish_paths)}"\n    )\n'''
        text = replace_once(text, anchor, debug_helper + anchor, "kuaishou comment-region debug helper")

    root_anchor = '            comments = comments_res.get("rootCommentsV2", [])\n'
    legacy_root = root_anchor + f'            _ks_enrich_comment_regions(comments_res, comments)  # {MARKER}\n'
    root_new = (
        root_anchor
        + f'            _ks_root_region_count = _ks_enrich_comment_regions(comments_res, comments)  # {MARKER}\n'
        + '            if comments and _ks_root_region_count == 0:\n'
        + '                _ks_comment_region_debug(comments_res, comments, "root")\n'
    )
    if legacy_root in text:
        text = text.replace(legacy_root, root_new, 1)
    elif root_new not in text:
        text = replace_once(text, root_anchor, root_new, "kuaishou root comment region enrichment")

    sub_anchor = '                sub_comments = comments_res.get("subCommentsV2", [])\n'
    legacy_sub = sub_anchor + f'                _ks_enrich_comment_regions(comments_res, sub_comments)  # {MARKER}\n'
    sub_new = (
        sub_anchor
        + f'                _ks_sub_region_count = _ks_enrich_comment_regions(comments_res, sub_comments)  # {MARKER}\n'
        + '                if sub_comments and _ks_sub_region_count == 0:\n'
        + '                    _ks_comment_region_debug(comments_res, sub_comments, "sub")\n'
    )
    if legacy_sub in text:
        text = text.replace(legacy_sub, sub_new, 1)
    elif sub_new not in text:
        text = replace_once(text, sub_anchor, sub_new, "kuaishou sub-comment region enrichment")

    text = text.replace(LEGACY_MARKER, MARKER)
    write_py(path, text)


def check(root: Path) -> dict:
    path = root / "media_platform/kuaishou/client.py"
    result = {
        "client_exists": path.exists(),
        "marker_present": False,
        "authorArea_supported": False,
        "root_enrichment": False,
        "sub_enrichment": False,
        "schema_debug_present": False,
        "ok": False,
    }
    if not path.exists():
        return result
    text = read(path)
    try:
        ast.parse(text, filename=str(path))
        result["marker_present"] = MARKER in text and LEGACY_MARKER not in text
        result["authorArea_supported"] = '"authorArea"' in text
        result["root_enrichment"] = "_ks_root_region_count = _ks_enrich_comment_regions(comments_res, comments)" in text
        result["sub_enrichment"] = "_ks_sub_region_count = _ks_enrich_comment_regions(comments_res, sub_comments)" in text
        result["schema_debug_present"] = "[KS_COMMENT_REGION_DEBUG]" in text
        result["ok"] = all([
            result["marker_present"],
            result["authorArea_supported"],
            result["root_enrichment"],
            result["sub_enrichment"],
            result["schema_debug_present"],
        ])
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Restore Kuaishou platform-displayed comment IP-region labels before JSONL storage.")
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    try:
        if args.check:
            result = check(root)
        else:
            patch_client(root)
            result = check(root)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"root": str(root), **result}, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
