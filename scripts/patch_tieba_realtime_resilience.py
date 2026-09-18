from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_TIEBA_REALTIME_RESILIENCE_V1"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_py(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def patch_core(root: Path) -> None:
    path = root / "media_platform/tieba/core.py"
    text = read(path)

    old_start = '''            if config.CRAWLER_TYPE == "search":
                # Search for notes and retrieve their comment information.
                await self.search()
                await self.get_specified_tieba_notes()
'''
    new_start = f'''            if config.CRAWLER_TYPE == "search":
                # Search for notes and retrieve their comment information.
                await self.search()
                # {MARKER}: realtime discovery does not fan out into the optional
                # forum-name crawl. Historical/backfill mode keeps that behavior.
                if os.environ.get("PROMOTION_WEEK_TIEBA_REALTIME_DISCOVERY") != "1":
                    await self.get_specified_tieba_notes()
'''
    if old_start in text:
        text = text.replace(old_start, new_start, 1)

    old_notes = '''                    if not notes_list:
                        utils.logger.info(
                            f"[BaiduTieBaCrawler.search] Search note list is empty"
                        )
                        break
                    utils.logger.info(
                        f"[BaiduTieBaCrawler.search] Note list len: {len(notes_list)}"
                    )
                    await self.get_specified_notes(
'''
    new_notes = f'''                    if not notes_list:
                        utils.logger.info(
                            f"[BaiduTieBaCrawler.search] Search note list is empty"
                        )
                        break
                    if os.environ.get("PROMOTION_WEEK_TIEBA_REALTIME_DISCOVERY") == "1":
                        try:
                            _promotion_week_tieba_limit = int(
                                os.environ.get("PROMOTION_WEEK_TIEBA_REALTIME_ITEMS_PER_KEYWORD", "4")
                            )
                        except Exception:
                            _promotion_week_tieba_limit = 4
                        _promotion_week_tieba_limit = max(1, min(_promotion_week_tieba_limit, 10))
                        notes_list = notes_list[:_promotion_week_tieba_limit]
                        utils.logger.info(
                            f"[BaiduTieBaCrawler.search] {MARKER} realtime items/keyword={{len(notes_list)}}"
                        )
                    utils.logger.info(
                        f"[BaiduTieBaCrawler.search] Note list len: {{len(notes_list)}}"
                    )
                    await self.get_specified_notes(
'''
    if old_notes in text and "_promotion_week_tieba_limit" not in text:
        text = text.replace(old_notes, new_notes, 1)

    old_page = '''                    page += 1
                except Exception as ex:
'''
    new_page = f'''                    page += 1
                    if os.environ.get("PROMOTION_WEEK_TIEBA_REALTIME_DISCOVERY") == "1":
                        # {MARKER}: one bounded search page per keyword in realtime.
                        break
                except Exception as ex:
'''
    if old_page in text and "one bounded search page per keyword" not in text:
        text = text.replace(old_page, new_page, 1)

    write_py(path, text)


def patch_client(root: Path) -> None:
    path = root / "media_platform/tieba/client.py"
    text = read(path)

    if "\nimport os\n" not in text:
        text = text.replace("import json\n", "import json\nimport os\n", 1)

    old_ensure = '''        if not self.playwright_page.url.startswith(self._host):
            await self.playwright_page.goto(self._host, wait_until="domcontentloaded")
'''
    new_ensure = f'''        if not self.playwright_page.url.startswith(self._host):
            await self.playwright_page.goto(
                self._host, wait_until="domcontentloaded", timeout=20000
            )  # {MARKER}
'''
    if old_ensure in text:
        text = text.replace(old_ensure, new_ensure, 1)

    old_for = '''        all_sub_comments: List[TiebaComment] = []

        for parment_comment in comments:
'''
    new_for = f'''        all_sub_comments: List[TiebaComment] = []
        _promotion_week_tieba_root_cap = 0
        _promotion_week_tieba_page_cap = 0
        if os.environ.get("PROMOTION_WEEK_TIEBA_REALTIME_DETAIL") == "1":
            try:
                _promotion_week_tieba_root_cap = max(
                    0, min(int(os.environ.get("PROMOTION_WEEK_TIEBA_SUBCOMMENT_ROOT_CAP", "3")), 10)
                )
            except Exception:
                _promotion_week_tieba_root_cap = 3
            try:
                _promotion_week_tieba_page_cap = max(
                    0, min(int(os.environ.get("PROMOTION_WEEK_TIEBA_SUBCOMMENT_PAGE_CAP", "1")), 5)
                )
            except Exception:
                _promotion_week_tieba_page_cap = 1

        for _promotion_week_tieba_root_index, parment_comment in enumerate(comments):
            if _promotion_week_tieba_root_cap and _promotion_week_tieba_root_index >= _promotion_week_tieba_root_cap:
                utils.logger.info(
                    "[BaiduTieBaClient.get_comments_all_sub_comments] {MARKER} realtime root cap reached"
                )
                break
'''
    if old_for in text and "_promotion_week_tieba_root_cap" not in text:
        text = text.replace(old_for, new_for, 1)

    old_while = '''            while max_sub_page_num >= current_page:
                # Construct sub-comment URL
'''
    new_while = f'''            while max_sub_page_num >= current_page:
                if _promotion_week_tieba_page_cap and current_page > _promotion_week_tieba_page_cap:
                    utils.logger.info(
                        "[BaiduTieBaClient.get_comments_all_sub_comments] {MARKER} realtime page cap reached"
                    )
                    break
                # Construct sub-comment URL
'''
    if old_while in text and "realtime page cap reached" not in text:
        text = text.replace(old_while, new_while, 1)

    text = text.replace(
        'await self.playwright_page.goto(sub_comment_url, wait_until="domcontentloaded")',
        'await self.playwright_page.goto(sub_comment_url, wait_until="domcontentloaded", timeout=20000)',
    )

    write_py(path, text)


def check(root: Path) -> dict:
    core = root / "media_platform/tieba/core.py"
    client = root / "media_platform/tieba/client.py"
    result = {
        "patch_version": 1,
        "core_exists": core.exists(),
        "client_exists": client.exists(),
        "bounded_search_page": False,
        "bounded_items_per_keyword": False,
        "skip_forum_fanout": False,
        "bounded_origin_navigation": False,
        "subcomment_root_cap": False,
        "subcomment_page_cap": False,
        "ok": False,
    }
    if not core.exists() or not client.exists():
        return result
    try:
        core_text = read(core)
        client_text = read(client)
        ast.parse(core_text, filename=str(core))
        ast.parse(client_text, filename=str(client))
        result["bounded_search_page"] = "one bounded search page per keyword" in core_text
        result["bounded_items_per_keyword"] = "PROMOTION_WEEK_TIEBA_REALTIME_ITEMS_PER_KEYWORD" in core_text
        result["skip_forum_fanout"] = "PROMOTION_WEEK_TIEBA_REALTIME_DISCOVERY" in core_text and "get_specified_tieba_notes" in core_text
        result["bounded_origin_navigation"] = 'wait_until="domcontentloaded", timeout=20000' in client_text
        result["subcomment_root_cap"] = "PROMOTION_WEEK_TIEBA_SUBCOMMENT_ROOT_CAP" in client_text
        result["subcomment_page_cap"] = "PROMOTION_WEEK_TIEBA_SUBCOMMENT_PAGE_CAP" in client_text
        result["ok"] = all(result[k] for k in (
            "bounded_search_page",
            "bounded_items_per_keyword",
            "skip_forum_fanout",
            "bounded_origin_navigation",
            "subcomment_root_cap",
            "subcomment_page_cap",
        ))
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Bound Tieba realtime discovery and nested-comment fan-out.")
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    try:
        if not args.check:
            patch_core(root)
            patch_client(root)
        result = check(root)
    except Exception as exc:
        print(json.dumps({"ok": False, "root": str(root), "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"root": str(root), **result}, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
