from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_BILI_REALTIME_COMMENT_BOUNDS_V1"


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
    path = root / "media_platform/bilibili/client.py"
    text = read(path)

    if "import os\n" not in text:
        anchor = "import json\n"
        if anchor not in text:
            raise RuntimeError("Bilibili client os import anchor missing")
        text = text.replace(anchor, anchor + "import os\n", 1)

    if f"# {MARKER}: bounded realtime sub-comment roots" not in text:
        old = '''        result = []
        is_end = False
        next_page = 0
        max_retries = 3
        is_first_page = True
'''
        new = f'''        result = []
        is_end = False
        next_page = 0
        max_retries = 3
        is_first_page = True

        # {MARKER}: bounded realtime sub-comment roots.
        # Exhaustive historical/deep runs are unchanged. Only the realtime
        # detail subprocess receives these environment variables.
        _bili_realtime_detail = os.environ.get(
            "PROMOTION_WEEK_BILI_REALTIME_DETAIL", ""
        ).strip() == "1"
        try:
            _bili_subcomment_root_cap = max(
                0,
                int(os.environ.get("PROMOTION_WEEK_BILI_SUBCOMMENT_ROOT_CAP", "0") or 0),
            )
        except Exception:
            _bili_subcomment_root_cap = 0
        _bili_subcomment_roots_used = 0
'''
        text = replace_once(text, old, new, "Bilibili realtime root budget setup")

    if f"# {MARKER}: enforce realtime root cap" not in text:
        old = '''            if is_fetch_sub_comments:
                for comment in comment_list:
                    comment_id = comment['rpid']
                    if (comment.get("rcount", 0) > 0):
                        await self.get_video_all_level_two_comments(
                            video_id,
                            comment_id,
                            CommentOrderType.DEFAULT,
                            10,
                            crawl_interval,
                            callback,
                        )
'''
        new = f'''            if is_fetch_sub_comments:
                for comment in comment_list:
                    comment_id = comment['rpid']
                    if (comment.get("rcount", 0) > 0):
                        # {MARKER}: enforce realtime root cap.
                        if (
                            _bili_realtime_detail
                            and _bili_subcomment_root_cap > 0
                            and _bili_subcomment_roots_used >= _bili_subcomment_root_cap
                        ):
                            continue
                        _bili_subcomment_roots_used += 1
                        await self.get_video_all_level_two_comments(
                            video_id,
                            comment_id,
                            CommentOrderType.DEFAULT,
                            10,
                            crawl_interval,
                            callback,
                        )
'''
        text = replace_once(text, old, new, "Bilibili realtime sub-comment root cap")

    if f"# {MARKER}: bounded realtime sub-comment pages" not in text:
        old = '''        pn = 1
        while True:
            result = await self.get_video_level_two_comments(video_id, level_one_comment_id, pn, ps, order_mode)
            comment_list: List[Dict] = result.get("replies", [])
            if callback:  # If there is a callback function, execute it
                await callback(video_id, comment_list)
            await asyncio.sleep(crawl_interval)
            if (int(result["page"]["count"]) <= pn * ps):
                break

            pn += 1
'''
        new = f'''        pn = 1
        _bili_realtime_detail = os.environ.get(
            "PROMOTION_WEEK_BILI_REALTIME_DETAIL", ""
        ).strip() == "1"
        try:
            _bili_subcomment_page_cap = max(
                0,
                int(os.environ.get("PROMOTION_WEEK_BILI_SUBCOMMENT_PAGE_CAP", "0") or 0),
            )
        except Exception:
            _bili_subcomment_page_cap = 0

        while True:
            result = await self.get_video_level_two_comments(video_id, level_one_comment_id, pn, ps, order_mode)
            comment_list: List[Dict] = result.get("replies", [])
            if callback:  # If there is a callback function, execute it
                await callback(video_id, comment_list)
            await asyncio.sleep(crawl_interval)

            # {MARKER}: bounded realtime sub-comment pages.
            if (
                _bili_realtime_detail
                and _bili_subcomment_page_cap > 0
                and pn >= _bili_subcomment_page_cap
            ):
                utils.logger.info(
                    f"[BILIBILI_REALTIME_SUBCOMMENT_BOUND] "
                    f"video_id={{video_id}} root={{level_one_comment_id}} "
                    f"pages={{pn}} cap={{_bili_subcomment_page_cap}}"
                )
                break

            if (int(result["page"]["count"]) <= pn * ps):
                break

            pn += 1
'''
        text = replace_once(text, old, new, "Bilibili realtime sub-comment page cap")

    write_py(path, text)


def check(root: Path) -> dict:
    client = root / "media_platform/bilibili/client.py"
    result = {
        "patch_version": 1,
        "client_exists": client.exists(),
        "realtime_env_gate": False,
        "subcomment_root_cap": False,
        "subcomment_page_cap": False,
        "historical_unbounded_without_env": False,
        "ok": False,
    }
    if not client.exists():
        return result

    try:
        text = read(client)
        ast.parse(text, filename=str(client))
        result["realtime_env_gate"] = (
            "PROMOTION_WEEK_BILI_REALTIME_DETAIL" in text
            and f"# {MARKER}: bounded realtime sub-comment roots" in text
        )
        result["subcomment_root_cap"] = (
            "PROMOTION_WEEK_BILI_SUBCOMMENT_ROOT_CAP" in text
            and "_bili_subcomment_roots_used >= _bili_subcomment_root_cap" in text
        )
        result["subcomment_page_cap"] = (
            "PROMOTION_WEEK_BILI_SUBCOMMENT_PAGE_CAP" in text
            and "[BILIBILI_REALTIME_SUBCOMMENT_BOUND]" in text
        )
        result["historical_unbounded_without_env"] = (
            '_bili_realtime_detail = os.environ.get(' in text
            and "and _bili_subcomment_root_cap > 0" in text
            and "and _bili_subcomment_page_cap > 0" in text
        )
        result["ok"] = all([
            result["realtime_env_gate"],
            result["subcomment_root_cap"],
            result["subcomment_page_cap"],
            result["historical_unbounded_without_env"],
        ])
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Bound only Bilibili realtime nested-comment work; exhaustive non-realtime crawling remains unchanged."
    )
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    try:
        if not args.check:
            patch_client(root)
        result = check(root)
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "root": str(root),
            "error": f"{type(exc).__name__}: {exc}",
        }, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps({
        "root": str(root),
        **result,
        "purpose": "bilibili_realtime_nested_comment_bounds_without_changing_exhaustive_backfill",
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
