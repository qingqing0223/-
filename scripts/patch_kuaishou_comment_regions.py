from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_KS_COMMENT_REGION_RESTORE_V6"
LEGACY_MARKERS = (
    "PROMOTION_WEEK_KS_COMMENT_REGION_RESTORE_V1",
    "PROMOTION_WEEK_KS_COMMENT_REGION_RESTORE_V2",
    "PROMOTION_WEEK_KS_COMMENT_REGION_RESTORE_V3",
    "PROMOTION_WEEK_KS_COMMENT_REGION_RESTORE_V4",
    "PROMOTION_WEEK_KS_COMMENT_REGION_RESTORE_V5",
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
    return replace_once(text, "\n\nclass KuaiShouClient", block + "\n\nclass KuaiShouClient", label)


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


def _ks_merge_region_by_comment_id(target_comments, supplemental_comments):
    region_by_comment = {}
    for item in supplemental_comments or []:
        if not isinstance(item, dict):
            continue
        cid = _ks_comment_id(item)
        region = _ks_direct_public_region(item)
        if cid and region:
            region_by_comment[cid] = region
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
'''
    return insert_before_client(text, helper, "kuaishou base comment-region helpers")


def ensure_h5_helpers(text: str) -> str:
    if "async def _ks_h5_comment_regions" in text:
        return text
    helper = r'''

_KS_H5_COMMENT_REGION_URL = "https://kph8gvfz.m.chenzhongtech.com/rest/wd/photo/comment/list"


def _ks_flatten_h5_comment_items(payload):
    items = []
    stack = [payload]
    seen = set()
    while stack:
        obj = stack.pop()
        oid = id(obj)
        if oid in seen:
            continue
        seen.add(oid)
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in ("rootComments", "rootCommentsV2", "subComments", "subCommentsV2") and isinstance(value, list):
                    items.extend(item for item in value if isinstance(item, dict))
                elif key == "subCommentsMap" and isinstance(value, dict):
                    for entry in value.values():
                        if isinstance(entry, dict):
                            subs = entry.get("subComments") or entry.get("subCommentsV2") or []
                            if isinstance(subs, list):
                                items.extend(item for item in subs if isinstance(item, dict))
                if isinstance(value, (dict, list, tuple)):
                    stack.append(value)
        elif isinstance(obj, (list, tuple)):
            stack.extend(obj)
    deduped = []
    known = set()
    for item in items:
        cid = _ks_comment_id(item)
        key = cid or str(id(item))
        if key in known:
            continue
        known.add(key)
        deduped.append(item)
    return deduped


async def _ks_h5_comment_regions(client, photo_id):
    cache = getattr(client, "_ks_h5_comment_region_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(client, "_ks_h5_comment_region_cache", cache)
    cache_key = str(photo_id)
    if cache_key in cache:
        return cache[cache_key]

    headers = {
        "User-Agent": client.headers.get("User-Agent", ""),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://m.gifshow.com",
        "Referer": f"https://m.gifshow.com/fw/photo/{photo_id}",
    }
    cookies = {}
    if isinstance(getattr(client, "cookie_dict", None), dict):
        did = client.cookie_dict.get("did")
        if did:
            cookies["did"] = did

    async with make_async_client(proxy=client.proxy) as http_client:
        response = await http_client.request(
            method="POST",
            url=_KS_H5_COMMENT_REGION_URL,
            json={"photoId": str(photo_id), "count": 300},
            headers=headers,
            cookies=cookies or None,
            timeout=max(float(getattr(client, "timeout", 10) or 10), 15.0),
        )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Kuaishou H5 comment response is not a JSON object")
    items = _ks_flatten_h5_comment_items(payload)
    region_items = sum(1 for item in items if _ks_direct_public_region(item))
    top_keys = sorted(str(k) for k in payload.keys())[:20]
    utils.logger.info(
        f"[KS_COMMENT_REGION_H5] photo={photo_id} items={len(items)} "
        f"region_items={region_items} top_keys={top_keys} did_cookie={bool(cookies.get('did'))}"
    )
    cache[cache_key] = items
    return items
'''
    return insert_before_client(text, helper, "kuaishou H5 comment-region helpers")



def ensure_h5_comment_fetch_fallback(text: str) -> str:
    if "async def _ks_h5_comment_fallback_response" in text:
        return text
    helper = r'''


def _ks_h5_named_comment_lists(payload, names):
    found = []
    stack = [payload]
    seen = set()
    while stack:
        obj = stack.pop()
        oid = id(obj)
        if oid in seen:
            continue
        seen.add(oid)
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in names and isinstance(value, list):
                    found.extend(item for item in value if isinstance(item, dict))
                if isinstance(value, (dict, list, tuple)):
                    stack.append(value)
        elif isinstance(obj, (list, tuple)):
            stack.extend(item for item in obj if isinstance(item, (dict, list, tuple)))
    deduped = []
    known = set()
    for item in found:
        cid = _ks_comment_id(item)
        key = cid or str(id(item))
        if key in known:
            continue
        known.add(key)
        deduped.append(item)
    return deduped


def _ks_normalize_h5_comment(item, root_comment_id=""):
    if not isinstance(item, dict):
        return {}
    out = dict(item)
    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    user = item.get("user") if isinstance(item.get("user"), dict) else {}
    comment_id = (
        item.get("comment_id") or item.get("commentId") or item.get("id") or ""
    )
    author_id = (
        item.get("author_id") or item.get("authorId") or item.get("user_id")
        or item.get("userId") or author.get("id") or user.get("id") or ""
    )
    author_name = (
        item.get("author_name") or item.get("authorName") or item.get("user_name")
        or item.get("userName") or author.get("name") or user.get("name") or ""
    )
    content = (
        item.get("content") or item.get("comment") or item.get("commentContent")
        or item.get("text") or ""
    )
    timestamp = (
        item.get("timestamp") or item.get("create_time") or item.get("createTime")
        or item.get("time") or 0
    )
    sub_count = (
        item.get("commentCount") or item.get("subCommentCount")
        or item.get("sub_comment_count") or 0
    )
    region = _ks_direct_public_region(item)
    out["comment_id"] = comment_id
    out["author_id"] = author_id
    out["author_name"] = author_name
    out["content"] = content
    out["timestamp"] = timestamp
    out["commentCount"] = sub_count
    out["hasSubComments"] = bool(
        item.get("hasSubComments")
        or item.get("has_sub_comments")
        or (str(sub_count).isdigit() and int(sub_count) > 0)
    )
    if region:
        out["ip_location"] = region
        out.setdefault("authorArea", region)
    root_id = str(
        root_comment_id
        or item.get("root_comment_id")
        or item.get("rootCommentId")
        or item.get("parent_comment_id")
        or item.get("parentCommentId")
        or ""
    ).strip()
    if root_id:
        out["parent_comment_id"] = root_id
        out["root_comment_id"] = root_id
    return out


async def _ks_h5_comment_payload(client, photo_id):
    cache = getattr(client, "_ks_h5_comment_payload_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(client, "_ks_h5_comment_payload_cache", cache)
    cache_key = str(photo_id)
    if cache_key in cache:
        return cache[cache_key]

    headers = {
        "User-Agent": client.headers.get("User-Agent", ""),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://m.gifshow.com",
        "Referer": f"https://m.gifshow.com/fw/photo/{photo_id}",
    }
    cookies = {}
    if isinstance(getattr(client, "cookie_dict", None), dict):
        for key in ("did", "didv", "kpf", "kpn"):
            value = client.cookie_dict.get(key)
            if value:
                cookies[key] = value

    async with make_async_client(proxy=client.proxy) as http_client:
        response = await http_client.request(
            method="POST",
            url=_KS_H5_COMMENT_REGION_URL,
            json={"photoId": str(photo_id), "count": 300},
            headers=headers,
            cookies=cookies or None,
            timeout=max(float(getattr(client, "timeout", 10) or 10), 15.0),
        )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Kuaishou H5 comment fallback response is not a JSON object")
    cache[cache_key] = payload
    return payload


def _ks_h5_root_fallback(payload):
    roots = _ks_h5_named_comment_lists(payload, {"rootComments", "rootCommentsV2"})
    normalized = []
    for item in roots:
        if not isinstance(item, dict):
            continue
        row = _ks_normalize_h5_comment(item)
        root_id = str(row.get("comment_id") or "").strip()
        if root_id:
            subs = _ks_h5_sub_fallback(payload, root_id)
            if subs:
                row["commentCount"] = len(subs)
                row["subCommentCount"] = len(subs)
                row["hasSubComments"] = True
        normalized.append(row)
    return normalized


def _ks_h5_public_comment_count(payload, roots=None):
    if isinstance(payload, dict):
        for key in ("commentCount", "commentCountV2", "totalCommentCount", "commentsCount"):
            value = payload.get(key)
            if value not in (None, ""):
                try:
                    return int(value)
                except Exception:
                    pass
    roots = roots or []
    total = len(roots)
    for root in roots:
        if not isinstance(root, dict):
            continue
        try:
            total += max(0, int(root.get("commentCount") or root.get("subCommentCount") or 0))
        except Exception:
            pass
    return total


def _ks_h5_sub_fallback(payload, root_comment_id):
    root_text = str(root_comment_id)
    matched = []

    stack = [payload]
    seen = set()
    while stack:
        obj = stack.pop()
        oid = id(obj)
        if oid in seen:
            continue
        seen.add(oid)
        if isinstance(obj, dict):
            sub_map = obj.get("subCommentsMap")
            if isinstance(sub_map, dict):
                direct = sub_map.get(root_text)
                if isinstance(direct, dict):
                    matched.extend(
                        _ks_h5_named_comment_lists(
                            direct, {"subComments", "subCommentsV2"}
                        )
                    )
                elif isinstance(direct, list):
                    matched.extend(item for item in direct if isinstance(item, dict))
            for key, value in obj.items():
                if key in {"subComments", "subCommentsV2"} and isinstance(value, list):
                    for item in value:
                        if not isinstance(item, dict):
                            continue
                        candidate_root = str(
                            item.get("root_comment_id")
                            or item.get("rootCommentId")
                            or item.get("parent_comment_id")
                            or item.get("parentCommentId")
                            or ""
                        )
                        if candidate_root == root_text:
                            matched.append(item)
                if isinstance(value, (dict, list, tuple)):
                    stack.append(value)
        elif isinstance(obj, (list, tuple)):
            stack.extend(item for item in obj if isinstance(item, (dict, list, tuple)))

    deduped = []
    known = set()
    for item in matched:
        cid = _ks_comment_id(item)
        key = cid or str(id(item))
        if key in known:
            continue
        known.add(key)
        deduped.append(_ks_normalize_h5_comment(item, root_text))
    return deduped


async def _ks_h5_comment_fallback_response(client, photo_id, root_comment_id=""):
    payload = await _ks_h5_comment_payload(client, photo_id)
    if root_comment_id:
        comments = _ks_h5_sub_fallback(payload, root_comment_id)
        utils.logger.info(
            f"[KS_COMMENT_H5_FETCH_FALLBACK] label=sub photo={photo_id} "
            f"root={root_comment_id} comments={len(comments)}"
        )
        return {"result": 1, "pcursorV2": "no_more", "subCommentsV2": comments}

    comments = _ks_h5_root_fallback(payload)
    public_count = _ks_h5_public_comment_count(payload, comments)
    utils.logger.info(
        f"[KS_COMMENT_H5_FETCH_FALLBACK] label=root photo={photo_id} "
        f"roots={len(comments)} public_comment_count={public_count}"
    )
    return {
        "result": 1,
        "pcursorV2": "no_more",
        "commentCountV2": public_count,
        "rootCommentsV2": comments,
    }
'''
    return insert_before_client(text, helper, "kuaishou H5 comment fetch fallback")

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
    text = ensure_h5_helpers(text)
    text = ensure_h5_comment_fetch_fallback(text)
    text = ensure_debug_helper(text)

    # V6 in-place upgrade for machines that already carry the V5 patch.
    # Network transport failures (for example an httpx ReadTimeout with an empty
    # string message) may otherwise escape the REST fallback and only appear as
    # the generic core-level "may be been blocked" message.
    text = text.replace(
        "except DataFetchError as _ks_rest_exc:",
        "except (DataFetchError, httpx.TransportError) as _ks_rest_exc:",
    )
    text = text.replace(
        "detail={str(_ks_rest_exc)[:240]}",
        "detail={repr(_ks_rest_exc)[:240]}",
    )

    # Upgrade an already V5-patched client in place so a REST V2 rejection
    # can fall back to the public H5 comment representation instead of yielding
    # zero comment files. This does not bypass login/captcha/security checks.
    if "[KS_COMMENT_REST_BLOCKED] label=root" not in text:
        text = text.replace(
            '        result = await self.request_rest_v2("/rest/v/photo/comment/list", post_data)\n',
            '        try:\n'
            '            result = await self.request_rest_v2("/rest/v/photo/comment/list", post_data)\n'
            '        except (DataFetchError, httpx.TransportError) as _ks_rest_exc:\n'
            '            utils.logger.warning(\n'
            '                f"[KS_COMMENT_REST_BLOCKED] label=root photo={photo_id} " \
'
            '                f"type={type(_ks_rest_exc).__name__} detail={repr(_ks_rest_exc)[:240]}; " \
'
            '                "trying public H5 comment representation"\n'
            '            )\n'
            '            result = await _ks_h5_comment_fallback_response(self, photo_id)\n',
            1,
        )  # kuaishou root REST-block fallback upgrade
    if "[KS_COMMENT_REST_BLOCKED] label=sub" not in text:
        text = text.replace(
            '        result = await self.request_rest_v2("/rest/v/photo/comment/sublist", post_data)\n',
            '        try:\n'
            '            result = await self.request_rest_v2("/rest/v/photo/comment/sublist", post_data)\n'
            '        except (DataFetchError, httpx.TransportError) as _ks_rest_exc:\n'
            '            utils.logger.warning(\n'
            '                f"[KS_COMMENT_REST_BLOCKED] label=sub photo={photo_id} root={root_comment_id} " \
'
            '                f"type={type(_ks_rest_exc).__name__} detail={repr(_ks_rest_exc)[:240]}; " \
'
            '                "trying public H5 comment representation"\n'
            '            )\n'
            '            result = await _ks_h5_comment_fallback_response(self, photo_id, root_comment_id)\n',
            1,
        )  # kuaishou sub REST-block fallback upgrade

    # Upgrade V3 in place: keep the already-stable REST V2 comment chain, but use
    # the public H5 comment representation only as a same-comment-id region source.
    text = text.replace(
        "await _ks_graphql_root_regions(self, photo_id, pcursor)",
        "await _ks_h5_comment_regions(self, photo_id)",
    )
    text = text.replace(
        "await _ks_graphql_sub_regions(self, photo_id, root_comment_id, pcursor)",
        "await _ks_h5_comment_regions(self, photo_id)",
    )
    text = text.replace("[KS_COMMENT_REGION_GRAPHQL] label=root", "[KS_COMMENT_REGION_H5_MERGE] label=root")
    text = text.replace("[KS_COMMENT_REGION_GRAPHQL] label=sub", "[KS_COMMENT_REGION_H5_MERGE] label=sub")
    text = text.replace("[KS_COMMENT_REGION_GRAPHQL_FAILED] label=root", "[KS_COMMENT_REGION_H5_FAILED] label=root")
    text = text.replace("[KS_COMMENT_REGION_GRAPHQL_FAILED] label=sub", "[KS_COMMENT_REGION_H5_FAILED] label=sub")

    root_old = '        return await self.request_rest_v2("/rest/v/photo/comment/list", post_data)\n'
    if "[KS_COMMENT_REGION_H5_MERGE] label=root" not in text:
        root_new = f'''        try:\n            result = await self.request_rest_v2("/rest/v/photo/comment/list", post_data)\n        except (DataFetchError, httpx.TransportError) as _ks_rest_exc:\n            utils.logger.warning(\n                f"[KS_COMMENT_REST_BLOCKED] label=root photo={{photo_id}} " \
                f"type={{type(_ks_rest_exc).__name__}} detail={{repr(_ks_rest_exc)[:240]}}; " \
                "trying public H5 comment representation"\n            )\n            result = await _ks_h5_comment_fallback_response(self, photo_id)\n        _ks_root_comments = result.get("rootCommentsV2", [])\n        if _ks_root_comments and not any(_ks_direct_public_region(c) for c in _ks_root_comments):  # {MARKER}\n            try:\n                _ks_supplemental = await _ks_h5_comment_regions(self, photo_id)\n                _ks_merged = _ks_merge_region_by_comment_id(_ks_root_comments, _ks_supplemental)\n                utils.logger.info(f"[KS_COMMENT_REGION_H5_MERGE] label=root merged={{_ks_merged}} comments={{len(_ks_root_comments)}}")\n            except Exception as _ks_region_exc:\n                utils.logger.info(f"[KS_COMMENT_REGION_H5_FAILED] label=root type={{type(_ks_region_exc).__name__}} detail={{str(_ks_region_exc)[:240]}}")\n        return result\n'''
        text = replace_once(text, root_old, root_new, "kuaishou root H5 region fallback")

    sub_old = '        return await self.request_rest_v2("/rest/v/photo/comment/sublist", post_data)\n'
    if "[KS_COMMENT_REGION_H5_MERGE] label=sub" not in text:
        sub_new = f'''        try:\n            result = await self.request_rest_v2("/rest/v/photo/comment/sublist", post_data)\n        except (DataFetchError, httpx.TransportError) as _ks_rest_exc:\n            utils.logger.warning(\n                f"[KS_COMMENT_REST_BLOCKED] label=sub photo={{photo_id}} root={{root_comment_id}} " \
                f"type={{type(_ks_rest_exc).__name__}} detail={{repr(_ks_rest_exc)[:240]}}; " \
                "trying public H5 comment representation"\n            )\n            result = await _ks_h5_comment_fallback_response(self, photo_id, root_comment_id)\n        _ks_sub_comments = result.get("subCommentsV2", [])\n        if _ks_sub_comments and not any(_ks_direct_public_region(c) for c in _ks_sub_comments):  # {MARKER}\n            try:\n                _ks_supplemental = await _ks_h5_comment_regions(self, photo_id)\n                _ks_merged = _ks_merge_region_by_comment_id(_ks_sub_comments, _ks_supplemental)\n                utils.logger.info(f"[KS_COMMENT_REGION_H5_MERGE] label=sub merged={{_ks_merged}} comments={{len(_ks_sub_comments)}}")\n            except Exception as _ks_region_exc:\n                utils.logger.info(f"[KS_COMMENT_REGION_H5_FAILED] label=sub type={{type(_ks_region_exc).__name__}} detail={{str(_ks_region_exc)[:240]}}")\n        return result\n'''
        text = replace_once(text, sub_old, sub_new, "kuaishou sub H5 region fallback")

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


def patch_core_diagnostics(root: Path) -> bool:
    """Make Kuaishou comment failures diagnosable without changing platform verification behavior."""
    path = root / "media_platform/kuaishou/core.py"
    if not path.exists():
        return False
    text = read(path)
    if "[KUAISHOU_COMMENT_EXCEPTION]" in text:
        return True

    old_variants = (
        'f"[KuaishouCrawler.get_comments] may be been blocked, err:{e}"',
        'f"[KuaishouCrawler.get_comments] may be been blocked, err: {e}"',
    )
    replacement = (
        'f"[KUAISHOU_COMMENT_EXCEPTION] video_id={video_id} " '
        'f"type={type(e).__name__} detail={repr(e)[:500]}"'
    )
    for old in old_variants:
        if old in text:
            text = text.replace(old, replacement, 1)
            write_py(path, text)
            return True
    return False


def check(root: Path) -> dict:
    path = root / "media_platform/kuaishou/client.py"
    core_path = root / "media_platform/kuaishou/core.py"
    result = {
        "client_exists": path.exists(),
        "core_exists": core_path.exists(),
        "marker_present": False,
        "authorArea_supported": False,
        "root_enrichment": False,
        "sub_enrichment": False,
        "schema_debug_present": False,
        "h5_fallback_present": False,
        "h5_helpers_defined": False,
        "legacy_graphql_calls_present": False,
        "h5_comment_fetch_fallback_present": False,
        "transport_fallback_present": False,
        "core_diagnostics_present": False,
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
        result["h5_fallback_present"] = all([
            "[KS_COMMENT_REGION_H5_MERGE] label=root" in text,
            "[KS_COMMENT_REGION_H5_MERGE] label=sub" in text,
        ])
        result["h5_helpers_defined"] = all([
            "async def _ks_h5_comment_regions" in text,
            "_KS_H5_COMMENT_REGION_URL" in text,
            "def _ks_flatten_h5_comment_items" in text,
        ])
        result["legacy_graphql_calls_present"] = any([
            "await _ks_graphql_root_regions(" in text,
            "await _ks_graphql_sub_regions(" in text,
        ])
        result["h5_comment_fetch_fallback_present"] = all([
            "async def _ks_h5_comment_fallback_response" in text,
            "[KS_COMMENT_REST_BLOCKED] label=root" in text,
            "[KS_COMMENT_REST_BLOCKED] label=sub" in text,
            "[KS_COMMENT_H5_FETCH_FALLBACK] label=root" in text,
        ])
        result["transport_fallback_present"] = (
            "except (DataFetchError, httpx.TransportError) as _ks_rest_exc:" in text
            and "detail={repr(_ks_rest_exc)[:240]}" in text
        )
        if core_path.exists():
            try:
                core_text = read(core_path)
                ast.parse(core_text, filename=str(core_path))
                result["core_diagnostics_present"] = "[KUAISHOU_COMMENT_EXCEPTION]" in core_text
            except Exception:
                pass
        result["ok"] = all([
            result["marker_present"], result["authorArea_supported"],
            result["root_enrichment"], result["sub_enrichment"],
            result["schema_debug_present"], result["h5_fallback_present"],
            result["h5_helpers_defined"], result["h5_comment_fetch_fallback_present"],
            result["transport_fallback_present"],
            not result["legacy_graphql_calls_present"],
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
            patch_core_diagnostics(root)
            result = check(root)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"root": str(root), **result}, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
