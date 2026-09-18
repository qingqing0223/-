from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_BILI_REALTIME_COMMENT_ORDER_V1"


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

    if f"# {MARKER}: newest-first in realtime only" not in text:
        old = '''        max_retries = 3
        is_first_page = True
'''
        new = f'''        max_retries = 3
        is_first_page = True

        # {MARKER}: newest-first in realtime only.
        # Historical/backfill runs preserve upstream popularity ordering.
        _bili_realtime_comment_order = (
            CommentOrderType.TIME
            if os.environ.get("PROMOTION_WEEK_BILI_REALTIME_DETAIL", "").strip() == "1"
            else CommentOrderType.DEFAULT
        )
'''
        text = replace_once(text, old, new, "Bilibili realtime comment order setup")

    old_first = '''                    comments_res = await self.get_video_comments(video_id, CommentOrderType.DEFAULT, next_page)
'''
    new_first = '''                    comments_res = await self.get_video_comments(
                        video_id,
                        _bili_realtime_comment_order,
                        next_page,
                    )
'''
    if new_first not in text:
        text = replace_once(text, old_first, new_first, "Bilibili first-level realtime comment order")

    old_nested = '''                        await self.get_video_all_level_two_comments(
                            video_id,
                            comment_id,
                            CommentOrderType.DEFAULT,
                            10,
                            crawl_interval,
                            callback,
                        )
'''
    new_nested = '''                        await self.get_video_all_level_two_comments(
                            video_id,
                            comment_id,
                            _bili_realtime_comment_order,
                            10,
                            crawl_interval,
                            callback,
                        )
'''
    if new_nested not in text:
        text = replace_once(text, old_nested, new_nested, "Bilibili nested realtime comment order")

    write_py(path, text)


def check(root: Path) -> dict:
    client = root / "media_platform/bilibili/client.py"
    result = {
        "patch_version": 1,
        "client_exists": client.exists(),
        "realtime_env_gate": False,
        "first_level_time_order": False,
        "nested_time_order": False,
        "historical_default_order_preserved": False,
        "ok": False,
    }
    if not client.exists():
        return result

    try:
        text = read(client)
        ast.parse(text, filename=str(client))
        result["realtime_env_gate"] = (
            f"# {MARKER}: newest-first in realtime only" in text
            and "PROMOTION_WEEK_BILI_REALTIME_DETAIL" in text
        )
        result["first_level_time_order"] = (
            "comments_res = await self.get_video_comments(" in text
            and "_bili_realtime_comment_order," in text
        )
        result["nested_time_order"] = (
            "await self.get_video_all_level_two_comments(" in text
            and "comment_id,\n                            _bili_realtime_comment_order," in text
        )
        result["historical_default_order_preserved"] = (
            "Historical/backfill runs preserve upstream popularity ordering" in text
            and "else CommentOrderType.DEFAULT" in text
        )
        result["ok"] = all([
            result["realtime_env_gate"],
            result["first_level_time_order"],
            result["nested_time_order"],
            result["historical_default_order_preserved"],
        ])
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Use newest-first Bilibili comments only for realtime detail probes; historical/backfill ordering is unchanged."
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
        "purpose": "bilibili_realtime_newest_first_comments_historical_order_unchanged",
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
