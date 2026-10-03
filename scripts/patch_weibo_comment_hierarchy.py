from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_WB_COMMENT_HIERARCHY_V2"


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
    text = text.replace("PROMOTION_WEEK_WB_COMMENT_HIERARCHY_V1", MARKER)

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

    # Add the public nested-reply endpoint used by m.weibo.cn.  The normal client
    # request helper unwraps "data", which would discard top-level max_id fields,
    # so this method requests the Response object and normalizes the pagination
    # envelope itself while preserving all existing anti-abuse guards.
    if "async def get_note_sub_comments_page(" not in text:
        anchor = "    async def get_note_all_comments(\n"
        method = f'''    async def get_note_sub_comments_page(
        self,
        comment_id: str,
        max_id: int = 0,
        max_id_type: int = 0,
    ) -> Dict:
        """Get one public nested-reply page for a first-level Weibo comment.  # {MARKER}"""
        uri = "/comments/hotFlowChild"
        params = {{
            "cid": comment_id,
            "max_id": max_id,
            "max_id_type": max_id_type,
        }}
        headers = copy.copy(self.headers)
        headers["Referer"] = f"https://m.weibo.cn/comments/hotFlowChild?cid={{comment_id}}"
        headers["X-Requested-With"] = "XMLHttpRequest"
        headers["MWeibo-Pwa"] = "1"
        response = await self.get(uri, params, headers=headers, return_response=True)
        try:
            payload = response.json()
        except Exception as exc:
            raise DataFetchError(f"nested comment response is not JSON: {{exc}}")
        ok_code = payload.get("ok")
        if ok_code == 0:
            msg = str(payload.get("msg") or "response error")
            if msg in {{"暂无数据", "没有更多了"}}:
                return {{"data": [], "max_id": 0, "max_id_type": 0}}
            if any(token in msg for token in ("频繁", "验证", "异常", "安全", "访问受限")):
                raise WeiboAccessGuardError(f"WEIBO_VERIFY_REQUIRED {{msg}}")
            raise DataFetchError(msg)
        if ok_code != 1:
            raise DataFetchError(str(payload.get("msg") or "unknown response"))
        body = payload.get("data")
        if isinstance(body, dict):
            rows = body.get("data") or body.get("comments") or []
            next_max_id = body.get(
                "max_id",
                payload.get("max_id", 0),
            )
            next_max_id_type = body.get(
                "max_id_type",
                payload.get("max_id_type", 0),
            )
        elif isinstance(body, list):
            rows = body
            next_max_id = payload.get("max_id", 0)
            next_max_id_type = payload.get("max_id_type", 0)
        else:
            rows = []
            next_max_id = 0
            next_max_id_type = 0

        if not isinstance(rows, list):
            rows = []

        return {{
            "data": rows,
            "max_id": next_max_id,
            "max_id_type": next_max_id_type,
        }}

'''
        text = replace_once(text, anchor, method + anchor, "weibo child endpoint")

    # Upgrade already-patched V2 trees that still assume payload["data"]
    # is always a list. Weibo hotFlowChild can also return a nested envelope.
    legacy_payload = (
        '        rows = payload.get("data")\n'
        '        if not isinstance(rows, list):\n'
        '            rows = []\n'
        '        return {\n'
        '            "data": rows,\n'
        '            "max_id": payload.get("max_id", 0),\n'
        '            "max_id_type": payload.get("max_id_type", 0),\n'
        '        }\n'
    )
    nested_payload = (
        '        body = payload.get("data")\n'
        '        if isinstance(body, dict):\n'
        '            rows = body.get("data") or body.get("comments") or []\n'
        '            next_max_id = body.get(\n'
        '                "max_id",\n'
        '                payload.get("max_id", 0),\n'
        '            )\n'
        '            next_max_id_type = body.get(\n'
        '                "max_id_type",\n'
        '                payload.get("max_id_type", 0),\n'
        '            )\n'
        '        elif isinstance(body, list):\n'
        '            rows = body\n'
        '            next_max_id = payload.get("max_id", 0)\n'
        '            next_max_id_type = payload.get("max_id_type", 0)\n'
        '        else:\n'
        '            rows = []\n'
        '            next_max_id = 0\n'
        '            next_max_id_type = 0\n'
        '\n'
        '        if not isinstance(rows, list):\n'
        '            rows = []\n'
        '\n'
        '        return {\n'
        '            "data": rows,\n'
        '            "max_id": next_max_id,\n'
        '            "max_id_type": next_max_id_type,\n'
        '        }\n'
    )

    if legacy_payload in text:
        text = text.replace(
            legacy_payload,
            nested_payload,
            1,
        )

    # Replace the upstream embedded-only sub-comment helper with a bounded,
    # deduplicating paginator.  Historical backfill can naturally exhaust it;
    # realtime is bounded externally by the monitor's per-candidate timeout and
    # per-note comment cap.
    start = text.find("    @staticmethod\n    async def get_comments_all_sub_comments(")
    if start >= 0:
        end = text.find("\n    async def get_note_info_by_id", start)
        if end < 0:
            raise RuntimeError("weibo sub-comment helper end anchor not found")
        replacement = f'''    async def get_comments_all_sub_comments(
        self,
        note_id: str,
        comment_list: List[Dict],
        callback: Optional[Callable] = None,
        max_count: int = 100,
        crawl_interval: float = 1.0,
    ) -> List[Dict]:
        """Persist embedded replies and fetch remaining public child pages.  # {MARKER}"""
        if not config.ENABLE_GET_SUB_COMMENTS:
            utils.logger.info(
                "[WeiboClient.get_comments_all_sub_comments] Crawling sub_comment mode is not enabled"
            )
            return []

        result: List[Dict] = []
        seen_ids = set()
        limit = max(0, int(max_count or 0))
        if limit <= 0:
            return result

        async def emit(root_id: str, rows: List[Dict]) -> None:
            fresh: List[Dict] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                child_id = str(row.get("id") or "").strip()
                if not child_id or child_id in seen_ids:
                    continue
                parent_id = str(
                    row.get("reply_id")
                    or row.get("parent_comment_id")
                    or root_id
                    or ""
                ).strip()
                if not parent_id or parent_id == child_id:
                    parent_id = root_id
                row["parent_comment_id"] = parent_id
                row["root_comment_id"] = root_id
                seen_ids.add(child_id)
                fresh.append(row)
                result.append(row)
                if len(result) >= limit:
                    break
            if fresh and callback:
                await callback(note_id, fresh)

        for comment in comment_list:
            if len(result) >= limit:
                break
            if not isinstance(comment, dict):
                continue
            root_id = str(comment.get("id") or comment.get("root_comment_id") or "").strip()
            if not root_id:
                continue

            embedded = comment.get("comments")
            if isinstance(embedded, list) and embedded:
                await emit(root_id, embedded)
            if len(result) >= limit:
                break

            try:
                expected = int(comment.get("total_number") or 0)
            except Exception:
                expected = 0
            embedded_count = len(embedded) if isinstance(embedded, list) else 0
            if expected <= embedded_count:
                continue

            max_id = 0
            max_id_type = 0
            page_guard = 0
            while len(result) < limit:
                page_guard += 1
                if page_guard > 50:
                    utils.logger.warning(
                        f"[WeiboClient.get_comments_all_sub_comments] child pagination guard reached root={{root_id}}"
                    )
                    break
                page = await self.get_note_sub_comments_page(root_id, max_id, max_id_type)
                rows = page.get("data") or []
                if rows:
                    await emit(root_id, rows)
                next_max_id = page.get("max_id", 0)
                next_max_id_type = page.get("max_id_type", 0)
                try:
                    next_max_id_int = int(next_max_id or 0)
                except Exception:
                    next_max_id_int = 0
                if next_max_id_int == 0 or not rows:
                    break
                if next_max_id_int == max_id and next_max_id_type == max_id_type:
                    break
                max_id = next_max_id_int
                max_id_type = next_max_id_type
                if crawl_interval > 0:
                    await asyncio.sleep(crawl_interval)

        return result
'''
        text = text[:start] + replacement + text[end:]

    old_call = (
        "            sub_comment_result = await self.get_comments_all_sub_comments(note_id, comment_list, callback)\n"
        "            result.extend(sub_comment_result)\n"
    )
    new_call = (
        "            remaining = max(0, max_count - len(result))\n"
        "            sub_comment_result = await self.get_comments_all_sub_comments(\n"
        "                note_id, comment_list, callback, max_count=remaining, crawl_interval=crawl_interval\n"
        "            )\n"
        "            result.extend(sub_comment_result)\n"
    )
    if old_call in text:
        text = text.replace(old_call, new_call, 1)

    write_py(path, text)


def patch_store(root: Path) -> None:
    path = root / "store/weibo/__init__.py"
    text = read(path)
    text = text.replace("PROMOTION_WEEK_WB_COMMENT_HIERARCHY_V1", MARKER)

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
        "patch_version": 2,
        "client_exists": client.exists(),
        "store_exists": store.exists(),
        "root_tagging": False,
        "child_endpoint": False,
        "child_pagination": False,
        "child_dedupe": False,
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
        result["child_endpoint"] = (
            'async def get_note_sub_comments_page(' in client_text
            and '"/comments/hotFlowChild"' in client_text
            and 'body = payload.get("data")' in client_text
            and 'isinstance(body, dict)' in client_text
            and 'next_max_id = body.get(' in client_text
            and '"max_id"' in client_text
            and 'next_max_id_type = body.get(' in client_text
            and '"max_id_type"' in client_text
        )
        result["child_pagination"] = (
            "child pagination guard reached" in client_text
            and "max_id_type" in client_text
            and "await self.get_note_sub_comments_page" in client_text
        )
        result["child_dedupe"] = "seen_ids = set()" in client_text
        result["root_persistence"] = '"root_comment_id": str(comment_item.get("root_comment_id") or comment_id)' in store_text
        result["root_parent_empty"] = '"parent_comment_id": str(comment_item.get("parent_comment_id") or "")' in store_text
        result["ok"] = all((
            result["root_tagging"],
            result["child_endpoint"],
            result["child_pagination"],
            result["child_dedupe"],
            result["root_persistence"],
            result["root_parent_empty"],
        ))
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Persist Weibo first-level/nested parent-root hierarchy and public child pages.")
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
