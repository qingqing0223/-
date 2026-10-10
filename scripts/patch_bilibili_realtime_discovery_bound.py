from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

MARKER = "PROMOTION_WEEK_BILI_SEARCH_SCOPE_V3"
V2_MARKER = "PROMOTION_WEEK_BILI_REALTIME_SEARCH_WINDOW_V2"


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


def _call_uses(segment: str, arg_name: str, expression: str) -> bool:
    return bool(
        re.search(
            rf"\b{re.escape(arg_name)}\s*=\s*{re.escape(expression)}\s*,",
            segment,
        )
    )


def _existing_v2_window_is_compatible(segment: str) -> bool:
    """Accept the already-installed V2 formal-window implementation.

    Some student/local MediaCrawler trees were patched before V3 existed.  In
    those trees the search call already uses:
      order=_bili_search_order
      pubtime_begin_s=_bili_pub_begin_s
      pubtime_end_s=_bili_pub_end_s
    and _bili_search_order switches LAST_PUBLISH only in realtime while keeping
    SearchOrderType.DEFAULT for historical/backfill mode.

    V3 must preserve that working search-window logic and only add the realtime
    fan-out bound.
    """
    return all([
        "_bili_search_order" in segment,
        "_bili_pub_begin_s" in segment,
        "_bili_pub_end_s" in segment,
        "SearchOrderType.LAST_PUBLISH" in segment,
        "else SearchOrderType.DEFAULT" in segment,
        _call_uses(segment, "order", "_bili_search_order"),
        _call_uses(segment, "pubtime_begin_s", "_bili_pub_begin_s"),
        _call_uses(segment, "pubtime_end_s", "_bili_pub_end_s"),
    ])


def _owned_v3_window_is_compatible(segment: str) -> bool:
    return all([
        "_bili_order" in segment,
        "_bili_pubtime_begin_s" in segment,
        "_bili_pubtime_end_s" in segment,
        "SearchOrderType.LAST_PUBLISH" in segment,
        "else SearchOrderType.DEFAULT" in segment,
        _call_uses(segment, "order", "_bili_order"),
        _call_uses(segment, "pubtime_begin_s", "_bili_pubtime_begin_s"),
        _call_uses(segment, "pubtime_end_s", "_bili_pubtime_end_s"),
    ])


def _insert_compat_marker(segment: str) -> str:
    if MARKER in segment:
        return segment
    lines = segment.splitlines(keepends=True)
    for idx, line in enumerate(lines):
        if "videos_res = await self.bili_client.search_video_by_keyword(" in line:
            indent = line[: len(line) - len(line.lstrip())]
            lines.insert(
                idx,
                (
                    f"{indent}# {MARKER}: compatible existing formal-window "
                    "search retained; V3 adds realtime fan-out only.\n"
                ),
            )
            return "".join(lines)
    raise RuntimeError("Bilibili search_video_by_keyword call not found")


def _patch_search_call(segment: str) -> str:
    # IMPORTANT: several deployed MediaCrawler copies already contain the V2
    # search-window patch. Do not try to rewrite its call back through the
    # original literal order=SearchOrderType.DEFAULT anchor.
    if _existing_v2_window_is_compatible(segment):
        return _insert_compat_marker(segment)

    # Idempotency for trees already fully patched by this V3 implementation.
    if _owned_v3_window_is_compatible(segment):
        return _insert_compat_marker(segment)

    lines = segment.splitlines(keepends=True)
    call_idx = -1
    for idx, line in enumerate(lines):
        if "videos_res = await self.bili_client.search_video_by_keyword(" in line:
            call_idx = idx
            break
    if call_idx < 0:
        raise RuntimeError("Bilibili search_video_by_keyword call not found")

    # Fresh/unpatched upstream shape. Only this shape needs V3 to install its
    # own order/time-window variables. If a different partial patch is present,
    # fail descriptively rather than silently corrupting it.
    raw_order = bool(re.search(r"\border\s*=\s*SearchOrderType\.DEFAULT\s*,", segment))
    raw_begin = bool(re.search(r"\bpubtime_begin_s\s*=\s*0\s*,", segment))
    raw_end = bool(re.search(r"\bpubtime_end_s\s*=\s*0\s*,", segment))
    if not (raw_order and raw_begin and raw_end):
        state = {
            "v2_marker_present": V2_MARKER in segment,
            "has_v2_order_var": "_bili_search_order" in segment,
            "has_v2_begin_var": "_bili_pub_begin_s" in segment,
            "has_v2_end_var": "_bili_pub_end_s" in segment,
            "call_order_v2": _call_uses(segment, "order", "_bili_search_order"),
            "call_begin_v2": _call_uses(segment, "pubtime_begin_s", "_bili_pub_begin_s"),
            "call_end_v2": _call_uses(segment, "pubtime_end_s", "_bili_pub_end_s"),
        }
        raise RuntimeError(
            "Bilibili search window is partially patched or uses an unknown "
            f"shape; refusing destructive rewrite: {state}"
        )

    call_indent = lines[call_idx][: len(lines[call_idx]) - len(lines[call_idx].lstrip())]
    arg_indent = call_indent + "    "
    marker = (
        f'{call_indent}# {MARKER}: newest-first formal-window search.\n'
        f'{call_indent}# Realtime and one-time backfill share the same formal\n'
        f'{call_indent}# monitoring window; only realtime applies fan-out limits.\n'
        f'{call_indent}_bili_order = (\n'
        f'{arg_indent}SearchOrderType.LAST_PUBLISH\n'
        f'{arg_indent}if os.environ.get("PROMOTION_WEEK_BILI_SEARCH_ORDER", "").strip().lower() == "pubdate"\n'
        f'{arg_indent}else SearchOrderType.DEFAULT\n'
        f'{call_indent})\n'
        f'{call_indent}try:\n'
        f'{arg_indent}_bili_pubtime_begin_s = max(\n'
        f'{arg_indent}    0, int(os.environ.get("PROMOTION_WEEK_BILI_PUBTIME_BEGIN_S", "0") or 0)\n'
        f'{arg_indent})\n'
        f'{call_indent}except Exception:\n'
        f'{arg_indent}_bili_pubtime_begin_s = 0\n'
        f'{call_indent}try:\n'
        f'{arg_indent}_bili_pubtime_end_s = max(\n'
        f'{arg_indent}    0, int(os.environ.get("PROMOTION_WEEK_BILI_PUBTIME_END_S", "0") or 0)\n'
        f'{arg_indent})\n'
        f'{call_indent}except Exception:\n'
        f'{arg_indent}_bili_pubtime_end_s = 0\n'
    )
    lines.insert(call_idx, marker)
    segment = "".join(lines)

    segment = re.sub(
        r"\border\s*=\s*SearchOrderType\.DEFAULT\s*,",
        "order=_bili_order,",
        segment,
        count=1,
    )
    segment = re.sub(
        r"\bpubtime_begin_s\s*=\s*0\s*,(?:\s*#.*)?",
        "pubtime_begin_s=_bili_pubtime_begin_s,",
        segment,
        count=1,
    )
    segment = re.sub(
        r"\bpubtime_end_s\s*=\s*0\s*,(?:\s*#.*)?",
        "pubtime_end_s=_bili_pubtime_end_s,",
        segment,
        count=1,
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
        f'{i3}    int(os.environ.get("PROMOTION_WEEK_BILI_REALTIME_ITEMS_PER_KEYWORD", "3") or 3),\n'
        f'{i3}    len(video_list),\n'
        f'{i3}),\n'
        f'{i2})\n'
        f'{i1}except Exception:\n'
        f'{i2}_bili_realtime_items_per_keyword = min(3, len(video_list))\n'
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
        "patch_version": 3,
        "core_exists": core.exists(),
        "existing_v2_window_compatible": False,
        "owned_v3_window_compatible": False,
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

        v2_ok = _existing_v2_window_is_compatible(segment)
        v3_ok = _owned_v3_window_is_compatible(segment)
        result["existing_v2_window_compatible"] = v2_ok
        result["owned_v3_window_compatible"] = v3_ok

        result["realtime_env_gate"] = (
            "PROMOTION_WEEK_BILI_REALTIME_DISCOVERY" in segment
        )
        result["per_keyword_bound"] = (
            "PROMOTION_WEEK_BILI_REALTIME_ITEMS_PER_KEYWORD" in segment
            and "video_list = video_list[:_bili_realtime_items_per_keyword]" in segment
        )
        result["pubdate_order_support"] = (
            v2_ok
            or (
                "PROMOTION_WEEK_BILI_SEARCH_ORDER" in segment
                and "SearchOrderType.LAST_PUBLISH" in segment
                and _call_uses(segment, "order", "_bili_order")
            )
        )
        result["formal_window_support"] = (
            v2_ok
            or (
                "PROMOTION_WEEK_BILI_PUBTIME_BEGIN_S" in segment
                and "PROMOTION_WEEK_BILI_PUBTIME_END_S" in segment
                and _call_uses(segment, "pubtime_begin_s", "_bili_pubtime_begin_s")
                and _call_uses(segment, "pubtime_end_s", "_bili_pubtime_end_s")
            )
        )
        result["historical_default_preserved"] = (
            (v2_ok or v3_ok)
            and "else SearchOrderType.DEFAULT" in segment
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
            "Patch Bilibili search so realtime and exhaustive backfill share the formal "
            "monitoring window; preserve an existing compatible V2 search-window patch "
            "and add only the realtime per-keyword fan-out bound."
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
        "purpose": "bilibili_formal_window_backfill_plus_bounded_realtime_fanout",
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
