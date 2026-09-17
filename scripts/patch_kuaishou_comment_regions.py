from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_KS_COMMENT_REGION_RESTORE_V3"
LEGACY_MARKERS = (
    "PROMOTION_WEEK_KS_COMMENT_REGION_RESTORE_V1",
    "PROMOTION_WEEK_KS_COMMENT_REGION_RESTORE_V2",
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


def patch_client(root: Path) -> None:
    path = root / "media_platform/kuaishou/client.py"
    text = read(path)
    for legacy in LEGACY_MARKERS:
        text = text.replace(legacy, MARKER)

    if "from tools.public_region import coarse_public_region" not in text:
        text = replace_once(
            text,
            "from tools import utils\n",
            "from tools import utils\nfrom tools.public_region import coarse_public_region  # " + MARKER + "\n",
            "kuaishou comment-region import",
        )

    if "def _ks_enrich_comment_regions" not in text:
        anchor = "\n\nclass KuaiShouClient"
        helper = '''\n\n_KS_COMMENT_REGION_KEYS = (\n    "authorArea", "author_area", "author_area_name", "authorRegion", "author_region",\n    "ip_location", "ipLocation", "ip_region", "ipRegion", "province", "province_name",\n    "region", "region_name", "location", "area",\n)\n\n\ndef _ks_direct_public_region(obj):\n    if not isinstance(obj, dict):\n        return ""\n    for key in _KS_COMMENT_REGION_KEYS:\n        value = obj.get(key)\n        if value not in (None, "") and not isinstance(value, (dict, list, tuple)):\n            region = coarse_public_region(value)\n            if region:\n                return region\n    for nested_key in ("author", "user", "userInfo", "user_info"):\n        nested = obj.get(nested_key)\n        if isinstance(nested, dict):\n            region = _ks_direct_public_region(nested)\n            if region:\n                return region\n    return ""\n\n\ndef _ks_comment_id(obj):\n    if not isinstance(obj, dict):\n        return ""\n    return str(obj.get("comment_id") or obj.get("commentId") or "").strip()\n\n\ndef _ks_author_id(obj):\n    if not isinstance(obj, dict):\n        return ""\n    return str(obj.get("author_id") or obj.get("authorId") or obj.get("user_id") or obj.get("userId") or "").strip()\n\n\ndef _ks_enrich_comment_regions(response, comments):\n    by_comment = {}\n    by_author = {}\n    generic_by_id = {}\n    stack = [response]\n    seen = set()\n    while stack:\n        obj = stack.pop()\n        oid = id(obj)\n        if oid in seen:\n            continue\n        seen.add(oid)\n        if isinstance(obj, dict):\n            region = _ks_direct_public_region(obj)\n            if region:\n                cid = _ks_comment_id(obj)\n                aid = _ks_author_id(obj)\n                if cid:\n                    by_comment[cid] = region\n                if aid:\n                    by_author[aid] = region\n                generic_id = str(obj.get("id") or "").strip()\n                if generic_id and any(k in obj for k in ("name", "user_name", "author_name", "headurl", "avatar")):\n                    generic_by_id[generic_id] = region\n            for key, value in obj.items():\n                key_low = str(key).lower()\n                if any(token in key_low for token in ("area", "region", "province", "location")) and isinstance(value, dict):\n                    for raw_id, raw_region in value.items():\n                        region2 = coarse_public_region(raw_region)\n                        if region2:\n                            generic_by_id[str(raw_id)] = region2\n                if isinstance(value, (dict, list, tuple)):\n                    stack.append(value)\n        elif isinstance(obj, (list, tuple)):\n            stack.extend(obj)\n    enriched = 0\n    for comment in comments or []:\n        if not isinstance(comment, dict):\n            continue\n        region = _ks_direct_public_region(comment)\n        if not region:\n            cid = _ks_comment_id(comment)\n            aid = _ks_author_id(comment)\n            region = by_comment.get(cid, "") or by_author.get(aid, "") or generic_by_id.get(aid, "")\n        if region:\n            comment["ip_location"] = region\n            comment.setdefault("authorArea", region)\n            enriched += 1\n    return enriched\n\n\ndef _ks_merge_region_by_comment_id(target_comments, supplemental_comments):\n    region_by_comment = {}\n    for item in supplemental_comments or []:\n        if not isinstance(item, dict):\n            continue\n        region = _ks_direct_public_region(item)\n        cid = _ks_comment_id(item)\n        if cid and region:\n            region_by_comment[cid] = region\n        for sub in item.get("subComments") or []:\n            if isinstance(sub, dict):\n                sub_region = _ks_direct_public_region(sub)\n                sub_id = _ks_comment_id(sub)\n                if sub_id and sub_region:\n                    region_by_comment[sub_id] = sub_region\n    merged = 0\n    for comment in target_comments or []:\n        if not isinstance(comment, dict):\n            continue\n        cid = _ks_comment_id(comment)\n        region = region_by_comment.get(cid, "")\n        if region:\n            comment["ip_location"] = region\n            comment.setdefault("authorArea", region)\n            merged += 1\n    return merged\n\n\n_KS_GRAPHQL_ROOT_REGION_QUERY = r"""\nquery commentListQuery($photoId: String, $pcursor: String) {\n  visionCommentList(photoId: $photoId, pcursor: $pcursor) {\n    pcursor\n    rootComments {\n      commentId\n      authorId\n      authorArea\n      subComments { commentId authorId authorArea }\n    }\n  }\n}\n"""\n\n_KS_GRAPHQL_SUB_REGION_QUERY = r"""\nmutation visionSubCommentList($photoId: String, $rootCommentId: String, $pcursor: String) {\n  visionSubCommentList(photoId: $photoId, rootCommentId: $rootCommentId, pcursor: $pcursor) {\n    pcursor\n    subComments { commentId authorId authorArea }\n  }\n}\n"""\n\n\nasync def _ks_graphql_root_regions(client, photo_id, pcursor=""):\n    data = await client.post("", {\n        "operationName": "commentListQuery",\n        "variables": {"photoId": str(photo_id), "pcursor": str(pcursor or "")},\n        "query": _KS_GRAPHQL_ROOT_REGION_QUERY,\n    })\n    payload = data.get("visionCommentList") or {}\n    return payload.get("rootComments") or []\n\n\nasync def _ks_graphql_sub_regions(client, photo_id, root_comment_id, pcursor=""):\n    data = await client.post("", {\n        "operationName": "visionSubCommentList",\n        "variables": {\n            "photoId": str(photo_id),\n            "rootCommentId": str(root_comment_id),\n            "pcursor": str(pcursor or ""),\n        },\n        "query": _KS_GRAPHQL_SUB_REGION_QUERY,\n    })\n    payload = data.get("visionSubCommentList") or {}\n    return payload.get("subComments") or []\n'''
        text = replace_once(text, anchor, helper + anchor, "kuaishou comment-region helper")

    if "def _ks_comment_region_debug" not in text:
        anchor = "\n\nclass KuaiShouClient"
        debug_helper = '''\n\ndef _ks_comment_region_debug(response, comments, label):\n    first_keys = []\n    if comments and isinstance(comments[0], dict):\n        first_keys = sorted(str(k) for k in comments[0].keys())\n    regionish_paths = set()\n    stack = [("response", response, 0)]\n    seen = set()\n    while stack:\n        prefix, obj, depth = stack.pop()\n        if depth > 5:\n            continue\n        oid = id(obj)\n        if oid in seen:\n            continue\n        seen.add(oid)\n        if isinstance(obj, dict):\n            for key, value in obj.items():\n                key_text = str(key)\n                path = f"{prefix}.{key_text}"\n                low = key_text.lower()\n                if any(token in low for token in ("area", "region", "province", "location", "ip")):\n                    regionish_paths.add(path)\n                if isinstance(value, (dict, list, tuple)):\n                    stack.append((path, value, depth + 1))\n        elif isinstance(obj, (list, tuple)):\n            for item in obj[:20]:\n                if isinstance(item, (dict, list, tuple)):\n                    stack.append((prefix + "[]", item, depth + 1))\n    utils.logger.info(\n        f"[KS_COMMENT_REGION_DEBUG] label={label} comments={len(comments or [])} "\n        f"first_comment_keys={first_keys} regionish_paths={sorted(regionish_paths)}"\n    )\n'''
        text = replace_once(text, anchor, debug_helper + anchor, "kuaishou comment-region debug helper")

    root_request_old = '        return await self.request_rest_v2("/rest/v/photo/comment/list", post_data)\n'
    root_request_new = f'''        result = await self.request_rest_v2("/rest/v/photo/comment/list", post_data)\n        _ks_root_comments = result.get("rootCommentsV2", [])\n        if _ks_root_comments and not any(_ks_direct_public_region(c) for c in _ks_root_comments):  # {MARKER}\n            try:\n                _ks_supplemental = await _ks_graphql_root_regions(self, photo_id, pcursor)\n                _ks_merged = _ks_merge_region_by_comment_id(_ks_root_comments, _ks_supplemental)\n                utils.logger.info(f"[KS_COMMENT_REGION_GRAPHQL] label=root merged={{_ks_merged}} comments={{len(_ks_root_comments)}}")\n            except Exception as _ks_region_exc:\n                utils.logger.info(f"[KS_COMMENT_REGION_GRAPHQL_FAILED] label=root type={{type(_ks_region_exc).__name__}}")\n        return result\n'''
    if root_request_new not in text:
        text = replace_once(text, root_request_old, root_request_new, "kuaishou root GraphQL region fallback")

    sub_request_old = '        return await self.request_rest_v2("/rest/v/photo/comment/sublist", post_data)\n'
    sub_request_new = f'''        result = await self.request_rest_v2("/rest/v/photo/comment/sublist", post_data)\n        _ks_sub_comments = result.get("subCommentsV2", [])\n        if _ks_sub_comments and not any(_ks_direct_public_region(c) for c in _ks_sub_comments):  # {MARKER}\n            try:\n                _ks_supplemental = await _ks_graphql_sub_regions(self, photo_id, root_comment_id, pcursor)\n                _ks_merged = _ks_merge_region_by_comment_id(_ks_sub_comments, _ks_supplemental)\n                utils.logger.info(f"[KS_COMMENT_REGION_GRAPHQL] label=sub merged={{_ks_merged}} comments={{len(_ks_sub_comments)}}")\n            except Exception as _ks_region_exc:\n                utils.logger.info(f"[KS_COMMENT_REGION_GRAPHQL_FAILED] label=sub type={{type(_ks_region_exc).__name__}}")\n        return result\n'''
    if sub_request_new not in text:
        text = replace_once(text, sub_request_old, sub_request_new, "kuaishou sub GraphQL region fallback")

    root_anchor = '            comments = comments_res.get("rootCommentsV2", [])\n'
    root_new = (
        root_anchor
        + f'            _ks_root_region_count = _ks_enrich_comment_regions(comments_res, comments)  # {MARKER}\n'
        + '            if comments and _ks_root_region_count == 0:\n'
        + '                _ks_comment_region_debug(comments_res, comments, "root")\n'
    )
    if "_ks_root_region_count = _ks_enrich_comment_regions" not in text:
        text = replace_once(text, root_anchor, root_new, "kuaishou root comment region enrichment")

    sub_anchor = '                sub_comments = comments_res.get("subCommentsV2", [])\n'
    sub_new = (
        sub_anchor
        + f'                _ks_sub_region_count = _ks_enrich_comment_regions(comments_res, sub_comments)  # {MARKER}\n'
        + '                if sub_comments and _ks_sub_region_count == 0:\n'
        + '                    _ks_comment_region_debug(comments_res, sub_comments, "sub")\n'
    )
    if "_ks_sub_region_count = _ks_enrich_comment_regions" not in text:
        text = replace_once(text, sub_anchor, sub_new, "kuaishou sub-comment region enrichment")

    for legacy in LEGACY_MARKERS:
        text = text.replace(legacy, MARKER)
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
        "graphql_fallback_present": False,
        "ok": False,
    }
    if not path.exists():
        return result
    text = read(path)
    try:
        ast.parse(text, filename=str(path))
        result["marker_present"] = MARKER in text and not any(m in text for m in LEGACY_MARKERS)
        result["authorArea_supported"] = '"authorArea"' in text
        result["root_enrichment"] = "_ks_root_region_count = _ks_enrich_comment_regions(comments_res, comments)" in text
        result["sub_enrichment"] = "_ks_sub_region_count = _ks_enrich_comment_regions(comments_res, sub_comments)" in text
        result["schema_debug_present"] = "[KS_COMMENT_REGION_DEBUG]" in text
        result["graphql_fallback_present"] = all([
            "_KS_GRAPHQL_ROOT_REGION_QUERY" in text,
            "_KS_GRAPHQL_SUB_REGION_QUERY" in text,
            "[KS_COMMENT_REGION_GRAPHQL]" in text,
        ])
        result["ok"] = all([
            result["marker_present"], result["authorArea_supported"],
            result["root_enrichment"], result["sub_enrichment"],
            result["schema_debug_present"], result["graphql_fallback_present"],
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
