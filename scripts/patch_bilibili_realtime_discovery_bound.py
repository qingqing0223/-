from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_BILI_REALTIME_DISCOVERY_V2"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_py(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def _function_bounds(text: str, class_name: str, method_name: str) -> tuple[int, int]:
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if (
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name == method_name
                ):
                    return offsets[child.lineno - 1], offsets[child.end_lineno]
    raise RuntimeError(f"{class_name}.{method_name} not found")


def _patch_search_call(segment: str) -> str:
    if MARKER in segment:
        return segment

    old = '''                videos_res = await self.bili_client.search_video_by_keyword(
                    keyword=keyword,
                    page=page,
                    page_size=bili_limit_count,
                    order=SearchOrderType.DEFAULT,
                    pubtime_begin_s=0,  # Publish date start timestamp
                    pubtime_end_s=0,  # Publish date end timestamp
                )
'''
    new = f'''                # {MARKER}: realtime search uses newest-first ordering and the
                # configured formal monitoring window. Historical/backfill subprocesses
                # do not set PROMOTION_WEEK_BILI_REALTIME_DISCOVERY and retain the
                # upstream comprehensive-search behavior.
                _bili_realtime = (
                    os.environ.get("PROMOTION_WEEK_BILI_REALTIME_DISCOVERY", "").strip()
                    == "1"
                )
                _bili_order = SearchOrderType.DEFAULT
                _bili_pubtime_begin_s = 0
                _bili_pubtime_end_s = 0
                if _bili_realtime:
                    if (
                        os.environ.get("PROMOTION_WEEK_BILI_SEARCH_ORDER", "")
                        .strip()
                        .lower()
                        == "pubdate"
                    ):
                        _bili_order = SearchOrderType.LAST_PUBLISH
                    try:
                        _bili_pubtime_begin_s = max(
                            0,
                            int(
                                os.environ.get(
                                    "PROMOTION_WEEK_BILI_PUBTIME_BEGIN_S",
                                    "0",
                                )
                                or 0
                            ),
                        )
                    except Exception:
                        _bili_pubtime_begin_s = 0
                    try:
                        _bili_pubtime_end_s = max(
                            0,
                            int(
                                os.environ.get(
                                    "PROMOTION_WEEK_BILI_PUBTIME_END_S",
                                    "0",
                                )
                                or 0
                            ),
                        )
                    except Exception:
                        _bili_pubtime_end_s = 0

                videos_res = await self.bili_client.search_video_by_keyword(
                    keyword=keyword,
                    page=page,
                    page_size=bili_limit_count,
                    order=_bili_order,
                    pubtime_begin_s=_bili_pubtime_begin_s,
                    pubtime_end_s=_bili_pubtime_end_s,
                )
'''
    if old not in segment:
        # A prior local patch may have changed comments/whitespace.  Fall back to
        # replacing the three argument lines inside search_by_keywords only.
        if (
            "order=SearchOrderType.DEFAULT," not in segment
            or "pubtime_begin_s=0" not in segment
            or "pubtime_end_s=0" not in segment
        ):
            raise RuntimeError("Bilibili realtime search-call anchor not found")

        marker = f'''                # {MARKER}: realtime search environment.
                _bili_realtime = (
                    os.environ.get("PROMOTION_WEEK_BILI_REALTIME_DISCOVERY", "").strip()
                    == "1"
                )
                _bili_order = (
                    SearchOrderType.LAST_PUBLISH
                    if _bili_realtime
                    and os.environ.get("PROMOTION_WEEK_BILI_SEARCH_ORDER", "").strip().lower()
                    == "pubdate"
                    else SearchOrderType.DEFAULT
                )
                try:
                    _bili_pubtime_begin_s = (
                        max(0, int(os.environ.get("PROMOTION_WEEK_BILI_PUBTIME_BEGIN_S", "0") or 0))
                        if _bili_realtime else 0
                    )
                except Exception:
                    _bili_pubtime_begin_s = 0
                try:
                    _bili_pubtime_end_s = (
                        max(0, int(os.environ.get("PROMOTION_WEEK_BILI_PUBTIME_END_S", "0") or 0))
                        if _bili_realtime else 0
                    )
                except Exception:
                    _bili_pubtime_end_s = 0
'''
        call_anchor = "                videos_res = await self.bili_client.search_video_by_keyword(\n"
        if call_anchor not in segment:
            raise RuntimeError("Bilibili search_video_by_keyword call not found")
        segment = segment.replace(call_anchor, marker + call_anchor, 1)
        segment = segment.replace(
            "                    order=SearchOrderType.DEFAULT,",
            "                    order=_bili_order,",
            1,
        )
        segment = segment.replace(
            "                    pubtime_begin_s=0,  # Publish date start timestamp",
            "                    pubtime_begin_s=_bili_pubtime_begin_s,",
            1,
        )
        segment = segment.replace(
            "                    pubtime_end_s=0,  # Publish date end timestamp",
            "                    pubtime_end_s=_bili_pubtime_end_s,",
            1,
        )
        return segment

    return segment.replace(old, new, 1)


def _patch_fanout_bound(segment: str) -> str:
    # V1 already installed on many student machines. Keep it and only add the V2
    # search-order/window logic above.
    if (
        "PROMOTION_WEEK_BILI_REALTIME_ITEMS_PER_KEYWORD" in segment
        and "video_list = video_list[:_bili_realtime_items_per_keyword]" in segment
    ):
        return segment

    old = '''                if not video_list:
                    utils.logger.info(f"[BilibiliCrawler.search_by_keywords] No more videos for '{keyword}', moving to next keyword.")
                    break

                semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
'''
    new = '''                if not video_list:
                    utils.logger.info(f"[BilibiliCrawler.search_by_keywords] No more videos for '{keyword}', moving to next keyword.")
                    break

                if os.environ.get("PROMOTION_WEEK_BILI_REALTIME_DISCOVERY", "").strip() == "1":
                    try:
                        _bili_realtime_items_per_keyword = max(
                            1,
                            min(
                                int(
                                    os.environ.get(
                                        "PROMOTION_WEEK_BILI_REALTIME_ITEMS_PER_KEYWORD",
                                        "5",
                                    )
                                    or 5
                                ),
                                len(video_list),
                            ),
                        )
                    except Exception:
                        _bili_realtime_items_per_keyword = min(5, len(video_list))

                    if len(video_list) > _bili_realtime_items_per_keyword:
                        utils.logger.info(
                            f"[BILIBILI_REALTIME_DISCOVERY_BOUND] "
                            f"keyword={keyword} original={len(video_list)} "
                            f"selected={_bili_realtime_items_per_keyword}"
                        )
                        video_list = video_list[:_bili_realtime_items_per_keyword]

                semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
'''
    if old not in segment:
        raise RuntimeError("Bilibili realtime fan-out anchor not found")
    return segment.replace(old, new, 1)


def patch_core(root: Path) -> None:
    path = root / "media_platform/bilibili/core.py"
    text = read(path)

    if "import os\n" not in text:
        anchor = "import asyncio\n"
        if anchor not in text:
            raise RuntimeError("Bilibili core os import anchor missing")
        text = text.replace(anchor, anchor + "import os\n", 1)

    start, end = _function_bounds(text, "BilibiliCrawler", "search_by_keywords")
    segment = text[start:end]
    segment = _patch_search_call(segment)
    segment = _patch_fanout_bound(segment)
    write_py(path, text[:start] + segment + text[end:])


def check(root: Path) -> dict:
    core = root / "media_platform/bilibili/core.py"
    result = {
        "patch_version": 2,
        "core_exists": core.exists(),
        "realtime_env_gate": False,
        "per_keyword_bound": False,
        "pubdate_order_support": False,
        "formal_window_support": False,
        "historical_default_preserved": False,
        "ok": False,
    }
    if not core.exists():
        return result

    try:
        text = read(core)
        ast.parse(text, filename=str(core))
        start, end = _function_bounds(text, "BilibiliCrawler", "search_by_keywords")
        segment = text[start:end]
        result["realtime_env_gate"] = (
            "PROMOTION_WEEK_BILI_REALTIME_DISCOVERY" in segment
        )
        result["per_keyword_bound"] = (
            "PROMOTION_WEEK_BILI_REALTIME_ITEMS_PER_KEYWORD" in segment
            and "video_list = video_list[:_bili_realtime_items_per_keyword]" in segment
        )
        result["pubdate_order_support"] = (
            "PROMOTION_WEEK_BILI_SEARCH_ORDER" in segment
            and "SearchOrderType.LAST_PUBLISH" in segment
        )
        result["formal_window_support"] = (
            "PROMOTION_WEEK_BILI_PUBTIME_BEGIN_S" in segment
            and "PROMOTION_WEEK_BILI_PUBTIME_END_S" in segment
            and "pubtime_begin_s=_bili_pubtime_begin_s" in segment
            and "pubtime_end_s=_bili_pubtime_end_s" in segment
        )
        result["historical_default_preserved"] = (
            "_bili_order = SearchOrderType.DEFAULT" in segment
            or "else SearchOrderType.DEFAULT" in segment
        )
        result["ok"] = all([
            result["realtime_env_gate"],
            result["per_keyword_bound"],
            result["pubdate_order_support"],
            result["formal_window_support"],
            result["historical_default_preserved"],
        ])
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Patch Bilibili realtime discovery so it is newest-first, constrained "
            "to the formal monitoring window, and bounded per keyword."
        )
    )
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    try:
        if not args.check:
            patch_core(root)
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
        "purpose": "bilibili_realtime_pubdate_window_and_bounded_fanout",
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
