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


def insert_before_client(text: str, block: str, label: str) -> str:
    anchor = "\n\nclass KuaiShouClient"
    return replace_once(text, anchor, block + anchor, label)


def ensure_base_helpers(text: str) -> str:
    if "def _ks_enrich_comment_regions" in text:
        return text
    helper = r'''

_KS_COMMENT_REGION_KEYS = (
    "authorArea", "author_area", "author_area_name", "authorRegion", "author_region",
    "ip_location", "ipLocation", "ip_region", "ipRegion", "province", "province_name",
    "region", "region_name", "location", "area",
)


def _ks_direct_public_region(obj):
    if not isinstance(obj, dict):
        return ""
    for key in _KS_COMMENT_REGION_KEYS:
        value = obj.get(key)
        if value not in (None, "") and not isinstance(value, (dict, list, tuple)):
            region = coarse_public_region(value)
            if region:
                return region
    for nested_key in ("author", "user", "userInfo", "user_info"):
        nested = obj.get(nested_key)
        if isinstance(nested, dict):
            region = _ks_direct_public_region(nested)
            if region:
                return region
    return ""


def _ks_comment_id(obj):
    if not isinstance(obj, dict):
        return ""
    return str(obj.get("comment_id") or obj.get("commentId") or "").strip()


def _ks_author_id(obj):
    if not isinstance(obj, dict):
        return ""
    return str(obj.get("author_id") or obj.get("authorId") or obj.get("user_id") or obj.get("userId") or "").strip()


def _ks_enrich_comment_regions(response, comments):
    by_comment = {}
    by_author = {}
    stack = [response]
    seen = set()
    while stack:
        obj = stack.pop()
        oid = id(obj)
        if oid in seen:
            continue
        seen.add(oid)
        if isinstance(obj, dict):
            region = _ks_direct_public_region(obj)
            if region:
                cid = _ks_comment_id(obj)
                aid = _ks_author_id(obj)
                if cid:
                    by_comment[cid] = region
                if aid:
                    by_author[aid] = region
            for value in obj.values():
                if isinstance(value, (dict, list, tuple)):
                    stack.append(value)
        elif isinstance(obj, (list, tuple)):
            stack.extend(obj)
    enriched = 0
    for comment in comments or []:
        if not isinstance(comment, dict):
            continue
        region = _ks_direct_public_region(comment)
        if not region:
            region = by_comment.get(_ks_comment_id(comment), "") or by_author.get(_ks_author_id(comment), "")
        if region:
            comment["ip_location"] = region
            comment.setdefault("authorArea", region)
            enriched += 1
    return enriched
'''
    return insert_before_client(text, helper, "kuaishou base comment-region helpers")


def ensure_graphql_helpers(text: str) -> str:
    if "async def _ks_graphql_root_regions" in text and "async def _ks_graphql_sub_regions" in text:
        return text
    helper = r'''


def _ks_merge_region_by_comment_id(target_comments, supplemental_comments):
    region_by_comment = {}
    for item in supplemental_comments or []:
        if not isinstance(item, dict):
            continue
        region = _ks_direct_public_region(item)
        cid = _ks_comment_id(item)
        if cid and region:
            region_by_comment[cid] = region
        for sub in item.get("subComments") or []:
            if isinstance(sub, dict):
                sub_region = _ks_direct_public_region(sub)
                sub_id = _ks_comment_id(sub)
                if sub_id and sub_region:
                    region_by_comment[sub_id] = sub_region
    merged = 0
    for comment in target_comments or []:
        if not isinstance(comment, dict):
            continue
        region = region_by_comment.get(_ks_comment_id(comment), "")
        if region:
            comment["ip_location"] = region
            comment.setdefault("authorArea", region)
            merged += 1
    return merged


_KS_GRAPHQL_ROOT_REGION_QUERY = r"""
query commentListQuery($photoId: String, $pcursor: String) {
  visionCommentList(photoId: $photoId, pcursor: $pcursor) {
    pcursor
    rootComments {
      commentId
      authorId
      authorArea
      subComments { commentId authorId authorArea }
    }
  }
}
"""

_KS_GRAPHQL_SUB_REGION_QUERY = r"""
mutation visionSubCommentList($photoId: String, $rootCommentId: String, $pcursor: String) {
  visionSubCommentList(photoId: $photoId, rootCommentId: $rootCommentId, pcursor: $pcursor) {
    pcursor
    subComments { commentId authorId authorArea }
  }
}
"""


async def _ks_graphql_root_regions(client, photo_id, pcursor=""):
    data = await client.post("", {
        "operationName": "commentListQuery",
        "variables": {"photoId": str(photo_id), "pcursor": str(pcursor or "")},
        "query": _KS_GRAPHQL_ROOT_REGION_QUERY,
    })
    payload = data.get("visionCommentList") or {}
    return payload.get("rootComments") or []


async def _ks_graphql_sub_regions(client, photo_id, root_comment_id, pcursor=""):
    data = await client.post("", {
        "operationName": "visionSubCommentList",
        "variables": {
            "photoId": str(photo_id),
            "rootCommentId": str(root_comment_id),
            "pcursor": str(pcursor or ""),
        },
        "query": _KS_GRAPHQL_SUB_REGION_QUERY,
    })
    payload = data.get("visionSubCommentList") or {}
    return payload.get("subComments") or []
'''
    return insert_before_client(text, helper, "kuaishou GraphQL comment-region helpers")


def ensure_debug_helper(text: str) -> str:
    if "def _ks_comment_region_debug" in text:
        return text
    helper = r'''


def _ks_comment_region_debug(response, comments, label):
    first_keys = []
    if comments and isinstance(comments[0], dict):
        first_keys = sorted(str(k) for k in comments[0].keys())
    regionish_paths = set()
    stack = [("response", response, 0)]
    seen = set()
    while stack:
        prefix, obj, depth = stack.pop()
        if depth > 5:
            continue
        oid = id(obj)
        if oid in seen:
            continue
        seen.add(oid)
        if isinstance(obj, dict):
            for key, value in obj.items():
                key_text = str(key)
                path = f"{prefix}.{key_text}"
                low = key_text.lower()
                if any(token in low for token in ("area", "region", "province", "location", "ip")):
                    regionish_paths.add(path)
                if isinstance(value, (dict, list, tuple)):
                    stack.append((path, value, depth + 1))
        elif isinstance(obj, (list, tuple)):
            for item in obj[:20]:
                if isinstance(item, (dict, list, tuple)):
                    stack.append((prefix + "[]", item, depth + 1))
    utils.logger.info(
        f"[KS_COMMENT_REGION_DEBUG] label={label} comments={len(comments or [])} "
        f"first_comment_keys={first_keys} regionish_paths={sorted(regionish_paths)}"
    )
'''
    return insert_before_client(text, helper, "kuaishou comment-region debug helper")


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

    text = ensure_base_helpers(text)
    text = ensure_graphql_helpers(text)
    text = ensure_debug_helper(text)

    root_old = '        return await self.request_rest_v2("/rest/v/photo/comment/list", post_data)\n'
    if "[KS_COMMENT_REGION_GRAPHQL] label=root" not in text:
        root_new = f'''        result = await self.request_rest_v2("/rest/v/photo/comment/list", post_data)\n        _ks_root_comments = result.get("rootCommentsV2", [])\n        if _ks_root_comments and not any(_ks_direct_public_region(c) for c in _ks_root_comments):  # {MARKER}\n            try:\n                _ks_supplemental = await _ks_graphql_root_regions(self, photo_id, pcursor)\n                _ks_merged = _ks_merge_region_by_comment_id(_ks_root_comments, _ks_supplemental)\n                utils.logger.info(f"[KS_COMMENT_REGION_GRAPHQL] label=root merged={{_ks_merged}} comments={{len(_ks_root_comments)}}")\n            except Exception as _ks_region_exc:\n                utils.logger.info(f"[KS_COMMENT_REGION_GRAPHQL_FAILED] label=root type={{type(_ks_region_exc).__name__}}")\n        return result\n'''
        text = replace_once(text, root_old, root_new, "kuaishou root GraphQL region fallback")

    sub_old = '        return await self.request_rest_v2("/rest/v/photo/comment/sublist", post_data)\n'
    if "[KS_COMMENT_REGION_GRAPHQL] label=sub" not in text:
        sub_new = f'''        result = await self.request_rest_v2("/rest/v/photo/comment/sublist", post_data)\n        _ks_sub_comments = result.get("subCommentsV2", [])\n        if _ks_sub_comments and not any(_ks_direct_public_region(c) for c in _ks_sub_comments):  # {MARKER}\n            try:\n                _ks_supplemental = await _ks_graphql_sub_regions(self, photo_id, root_comment_id, pcursor)\n                _ks_merged = _ks_merge_region_by_comment_id(_ks_sub_comments, _ks_supplemental)\n                utils.logger.info(f"[KS_COMMENT_REGION_GRAPHQL] label=sub merged={{_ks_merged}} comments={{len(_ks_sub_comments)}}")\n            except Exception as _ks_region_exc:\n                utils.logger.info(f"[KS_COMMENT_REGION_GRAPHQL_FAILED] label=sub type={{type(_ks_region_exc).__name__}}")\n        return result\n'''
        text = replace_once(text, sub_old, sub_new, "kuaishou sub GraphQL region fallback")

    root_anchor = '            comments = comments_res.get("rootCommentsV2", [])\n'
    if "_ks_root_region_count = _ks_enrich_comment_regions" not in text:
        text = replace_once(
            text,
            root_anchor,
            root_anchor
            + f'            _ks_root_region_count = _ks_enrich_comment_regions(comments_res, comments)  # {MARKER}\n'
            + '            if comments and _ks_root_region_count == 0:\n'
            + '                _ks_comment_region_debug(comments_res, comments, "root")\n',
            "kuaishou root comment region enrichment",
        )

    sub_anchor = '                sub_comments = comments_res.get("subCommentsV2", [])\n'
    if "_ks_sub_region_count = _ks_enrich_comment_regions" not in text:
        text = replace_once(
            text,
            sub_anchor,
            sub_anchor
            + f'                _ks_sub_region_count = _ks_enrich_comment_regions(comments_res, sub_comments)  # {MARKER}\n'
            + '                if sub_comments and _ks_sub_region_count == 0:\n'
            + '                    _ks_comment_region_debug(comments_res, sub_comments, "sub")\n',
            "kuaishou sub-comment region enrichment",
        )

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
        "graphql_helpers_defined": False,
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
            "[KS_COMMENT_REGION_GRAPHQL] label=root" in text,
            "[KS_COMMENT_REGION_GRAPHQL] label=sub" in text,
        ])
        result["graphql_helpers_defined"] = all([
            "async def _ks_graphql_root_regions" in text,
            "async def _ks_graphql_sub_regions" in text,
            "def _ks_merge_region_by_comment_id" in text,
        ])
        result["ok"] = all([
            result["marker_present"], result["authorArea_supported"],
            result["root_enrichment"], result["sub_enrichment"],
            result["schema_debug_present"], result["graphql_fallback_present"],
            result["graphql_helpers_defined"],
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
        result = check(root) if args.check else (patch_client(root) or check(root))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"root": str(root), **result}, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
