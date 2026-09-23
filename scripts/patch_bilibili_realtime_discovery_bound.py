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

    lines = segment.splitlines(keepends=True)
    call_idx = -1
    for idx, line in enumerate(lines):
        if "videos_res = await self.bili_client.search_video_by_keyword(" in line:
            call_idx = idx
            break
    if call_idx < 0:
        raise RuntimeError("Bilibili search_video_by_keyword call not found")

    call_indent = lines[call_idx][: len(lines[call_idx]) - len(lines[call_idx].lstrip())]
    arg_indent = call_indent + "    "
    marker = (
        f'{call_indent}# {MARKER}: realtime search uses newest-first ordering and the formal window.\n'
        f'{call_indent}_bili_realtime = (\n'
        f'{arg_indent}os.environ.get("PROMOTION_WEEK_BILI_REALTIME_DISCOVERY", "").strip() == "1"\n'
        f'{call_indent})\n'
        f'{call_indent}_bili_order = (\n'
        f'{arg_indent}SearchOrderType.LAST_PUBLISH\n'
        f'{arg_indent}if _bili_realtime\n'
        f'{arg_indent}and os.environ.get("PROMOTION_WEEK_BILI_SEARCH_ORDER", "").strip().lower() == "pubdate"\n'
        f'{arg_indent}else SearchOrderType.DEFAULT\n'
        f'{call_indent})\n'
        f'{call_indent}try:\n'
        f'{arg_indent}_bili_pubtime_begin_s = (\n'
        f'{arg_indent}    max(0, int(os.environ.get("PROMOTION_WEEK_BILI_PUBTIME_BEGIN_S", "0") or 0))\n'
        f'{arg_indent}    if _bili_realtime else 0\n'
        f'{arg_indent})\n'
        f'{call_indent}except Exception:\n'
        f'{arg_indent}_bili_pubtime_begin_s = 0\n'
        f'{call_indent}try:\n'
        f'{arg_indent}_bili_pubtime_end_s = (\n'
        f'{arg_indent}    max(0, int(os.environ.get("PROMOTION_WEEK_BILI_PUBTIME_END_S", "0") or 0))\n'
        f'{arg_indent}    if _bili_realtime else 0\n'
        f'{arg_indent})\n'
        f'{call_indent}except Exception:\n'
        f'{arg_indent}_bili_pubtime_end_s = 0\n'
    )
    lines.insert(call_idx, marker)
    segment = "".join(lines)

    if "order=SearchOrderType.DEFAULT," not in segment:
        raise RuntimeError("Bilibili search order argument not found")
    if "pubtime_begin_s=0" not in segment or "pubtime_end_s=0" not in segment:
        raise RuntimeError("Bilibili search time-window arguments not found")

    segment = segment.replace(
        "order=SearchOrderType.DEFAULT,",
        "order=_bili_order,",
        1,
    )
    segment = segment.replace(
        "pubtime_begin_s=0,  # Publish date start timestamp",
        "pubtime_begin_s=_bili_pubtime_begin_s,",
        1,
    )
    if "pubtime_begin_s=0" in segment:
        segment = segment.replace(
            "pubtime_begin_s=0,",
            "pubtime_begin_s=_bili_pubtime_begin_s,",
            1,
        )
    segment = segment.replace(
        "pubtime_end_s=0,  # Publish date end timestamp",
        "pubtime_end_s=_bili_pubtime_end_s,",
        1,
    )
    if "pubtime_end_s=0" in segment:
        segment = segment.replace(
            "pubtime_end_s=0,",
            "pubtime_end_s=_bili_pubtime_end_s,",
            1,
        )
    return segment

def _patch_fanout_bound(segment: str) -> str:
    if (
        "PROMOTION_WEEK_BILI_REALTIME_ITEMS_PER_KEYWORD" in segment
        and "video_list = video_list[:_bili_realtime_items_per_keyword]" in segment
    ):
        return segment

    lines = segment.splitlines(keepends=True)
    semaphore_idx = -1
    for idx, line in enumerate(lines):
        if "semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)" in line:
            semaphore_idx = idx
            break
    if semaphore_idx < 0:
        raise RuntimeError("Bilibili realtime fan-out semaphore anchor not found")

    indent = lines[semaphore_idx][: len(lines[semaphore_idx]) - len(lines[semaphore_idx].lstrip())]
    i1 = indent + "    "
    i2 = indent + "        "
    i3 = indent + "            "
    block = (
        f'{indent}if os.environ.get("PROMOTION_WEEK_BILI_REALTIME_DISCOVERY", "").strip() == "1":\n'
        f'{i1}try:\n'
        f'{i2}_bili_realtime_items_per_keyword = max(\n'
        f'{i3}1,\n'
        f'{i3}min(\n'
        f'{i3}    int(os.environ.get("PROMOTION_WEEK_BILI_REALTIME_ITEMS_PER_KEYWORD", "5") or 5),\n'
        f'{i3}    len(video_list),\n'
        f'{i3}),\n'
        f'{i2})\n'
        f'{i1}except Exception:\n'
        f'{i2}_bili_realtime_items_per_keyword = min(5, len(video_list))\n'
        f'{i1}if len(video_list) > _bili_realtime_items_per_keyword:\n'
        f'{i2}utils.logger.info(\n'
        f'{i3}f"[BILIBILI_REALTIME_DISCOVERY_BOUND] keyword={{keyword}} "\n'
        f'{i3}f"original={{len(video_list)}} selected={{_bili_realtime_items_per_keyword}}"\n'
        f'{i2})\n'
        f'{i2}video_list = video_list[:_bili_realtime_items_per_keyword]\n'
        f'\n'
    )
    lines.insert(semaphore_idx, block)
    return "".join(lines)

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
