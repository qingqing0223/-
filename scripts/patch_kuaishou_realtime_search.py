from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_KS_REALTIME_SEARCH_V2"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def _method_bounds(text: str, class_name: str, method_name: str) -> tuple[int, int]:
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                    return offsets[child.lineno - 1], offsets[child.end_lineno]
    raise RuntimeError(f"{class_name}.{method_name} not found")


def _patch_search_segment(segment: str) -> str:
    if MARKER in segment:
        return segment

    lines = segment.splitlines(keepends=True)
    append_idx = None
    for i, line in enumerate(lines):
        compact = line.replace(" ", "")
        if "video_id_list.append(" in compact and "video_detail" in compact:
            append_idx = i
            break
    if append_idx is None:
        raise RuntimeError("Kuaishou search-loop video_id_list.append anchor not found")

    indent = lines[append_idx][: len(lines[append_idx]) - len(lines[append_idx].lstrip())]
    guard = (
        f'{indent}# {MARKER}: bound live discovery without depending on one exact upstream loop shape.\n'
        f'{indent}if str(os.getenv("PROMOTION_WEEK_KS_REALTIME", "")).strip().lower() in {{"1", "true", "yes", "on"}}:\n'
        f'{indent}    try:\n'
        f'{indent}        _ks_rt_limit = max(1, int(os.getenv("PROMOTION_WEEK_KS_REALTIME_ITEMS_PER_KEYWORD", "5")))\n'
        f'{indent}    except Exception:\n'
        f'{indent}        _ks_rt_limit = 5\n'
        f'{indent}    if len(video_id_list) >= _ks_rt_limit:\n'
        f'{indent}        utils.logger.info(\n'
        f'{indent}            f"[KS_REALTIME_DISCOVERY_SLICE] keyword={{keyword}} limit={{_ks_rt_limit}} kept={{len(video_id_list)}}"\n'
        f'{indent}        )\n'
        f'{indent}        break\n'
    )
    lines.insert(append_idx, guard)
    return "".join(lines)


def patch(root: Path) -> None:
    path = root / "media_platform" / "kuaishou" / "core.py"
    if not path.exists():
        raise RuntimeError(f"Kuaishou core not found: {path}")
    text = _read(path)

    if "import os\n" not in text:
        text = text.replace("import asyncio\n", "import asyncio\nimport os\n", 1)

    start, end = _method_bounds(text, "KuaishouCrawler", "search")
    segment = text[start:end]

    # Upgrade the V1 rewrite, if present on a machine that ran an earlier test.
    if "PROMOTION_WEEK_KS_REALTIME_SEARCH_V1" in segment:
        segment = segment.replace("PROMOTION_WEEK_KS_REALTIME_SEARCH_V1", MARKER)
        _write(path, text[:start] + segment + text[end:])
        return

    patched = _patch_search_segment(segment)
    _write(path, text[:start] + patched + text[end:])


def check(root: Path) -> dict:
    path = root / "media_platform" / "kuaishou" / "core.py"
    result = {
        "patch_version": 2,
        "core_exists": path.exists(),
        "marker_present": False,
        "env_gate_present": False,
        "per_keyword_guard_present": False,
        "append_anchor_present": False,
        "historical_mode_untouched": False,
        "ok": False,
    }
    if not path.exists():
        return result
    text = _read(path)
    try:
        ast.parse(text, filename=str(path))
        start, end = _method_bounds(text, "KuaishouCrawler", "search")
        segment = text[start:end]
        result["marker_present"] = MARKER in segment
        result["env_gate_present"] = "PROMOTION_WEEK_KS_REALTIME" in segment
        result["per_keyword_guard_present"] = ("if len(video_id_list) >= _ks_rt_limit:" in segment or "_ks_feeds = _ks_feeds[:_ks_rt_limit]" in segment)
        result["append_anchor_present"] = "video_id_list.append(" in segment
        result["historical_mode_untouched"] = 'if str(os.getenv("PROMOTION_WEEK_KS_REALTIME"' in segment
        result["ok"] = all([
            result["marker_present"],
            result["env_gate_present"],
            result["per_keyword_guard_present"],
            result["append_anchor_present"],
            result["historical_mode_untouched"],
        ])
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    try:
        if not args.check:
            patch(root)
        result = check(root)
    except Exception as exc:
        print(json.dumps(
            {"ok": False, "error": f"{type(exc).__name__}: {exc}", "root": str(root)},
            ensure_ascii=False,
            indent=2,
        ))
        return 2
    print(json.dumps({"root": str(root), **result}, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
