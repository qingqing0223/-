from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_BILI_REALTIME_DISCOVERY_BOUND_V1"


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


def patch_core(root: Path) -> None:
    path = root / "media_platform/bilibili/core.py"
    text = read(path)

    if "import os\n" not in text:
        anchor = "import asyncio\n"
        if anchor not in text:
            raise RuntimeError("Bilibili core os import anchor missing")
        text = text.replace(anchor, anchor + "import os\n", 1)

    if f"# {MARKER}: bound realtime discovery detail fan-out" not in text:
        old = '''                if not video_list:
                    utils.logger.info(f"[BilibiliCrawler.search_by_keywords] No more videos for '{keyword}', moving to next keyword.")
                    break

                semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
'''
        new = f'''                if not video_list:
                    utils.logger.info(f"[BilibiliCrawler.search_by_keywords] No more videos for '{{keyword}}', moving to next keyword.")
                    break

                # {MARKER}: bound realtime discovery detail fan-out.
                # Bilibili returns up to 20 results per search page and upstream
                # immediately fetches full detail for every result. With six
                # monitoring keywords that means up to 120 detail API calls before
                # the realtime comment phase starts. Only realtime subprocesses set
                # this environment gate; historical/backfill behavior is unchanged.
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
                            f"keyword={{keyword}} original={{len(video_list)}} "
                            f"selected={{_bili_realtime_items_per_keyword}}"
                        )
                        video_list = video_list[:_bili_realtime_items_per_keyword]

                semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
'''
        text = replace_once(
            text,
            old,
            new,
            "Bilibili realtime discovery detail bound",
        )

    write_py(path, text)


def check(root: Path) -> dict:
    core = root / "media_platform/bilibili/core.py"
    result = {
        "patch_version": 1,
        "core_exists": core.exists(),
        "realtime_env_gate": False,
        "per_keyword_bound": False,
        "historical_unbounded_without_env": False,
        "log_marker": False,
        "ok": False,
    }
    if not core.exists():
        return result

    try:
        text = read(core)
        ast.parse(text, filename=str(core))
        result["realtime_env_gate"] = (
            "PROMOTION_WEEK_BILI_REALTIME_DISCOVERY" in text
            and f"# {MARKER}: bound realtime discovery detail fan-out" in text
        )
        result["per_keyword_bound"] = (
            "PROMOTION_WEEK_BILI_REALTIME_ITEMS_PER_KEYWORD" in text
            and "video_list = video_list[:_bili_realtime_items_per_keyword]" in text
        )
        result["historical_unbounded_without_env"] = (
            'os.environ.get("PROMOTION_WEEK_BILI_REALTIME_DISCOVERY", "").strip() == "1"'
            in text
        )
        result["log_marker"] = "[BILIBILI_REALTIME_DISCOVERY_BOUND]" in text
        result["ok"] = all([
            result["realtime_env_gate"],
            result["per_keyword_bound"],
            result["historical_unbounded_without_env"],
            result["log_marker"],
        ])
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Bound Bilibili realtime search detail fan-out per keyword while preserving exhaustive historical collection."
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
        "purpose": "bilibili_realtime_discovery_limits_detail_fanout_per_keyword",
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
