from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_KS_ENGAGEMENT_FIELDS_V1"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def _ensure_first_present_helper(text: str) -> str:
    if "def _ks_first_present(" in text:
        return text
    anchor = "\n\nclass KuaishouStoreFactory:\n"
    helper = f'''


def _ks_first_present(objects, *keys):
    """Return the first field that is actually present without inventing zero.

    Kuaishou search/detail/comment payloads use a mix of camelCase and snake_case.
    A missing field is kept as an empty string so downstream exports can
    distinguish "not returned" from a real platform value of 0.  # {MARKER}
    """
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        for key in keys:
            if key in obj and obj.get(key) is not None:
                return obj.get(key)
    return ""
'''
    return _replace_once(
        text,
        anchor,
        helper + anchor,
        "Kuaishou store helper insertion",
    )


def _function_bounds(lines: list[str], function_name: str) -> tuple[int, int]:
    start = -1
    for i, line in enumerate(lines):
        if line.startswith(f"async def {function_name}("):
            start = i
            break
    if start < 0:
        raise RuntimeError(f"function not found: {function_name}")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("async def ") or lines[i].startswith("def "):
            end = i
            break
    return start, end


def _replace_or_insert_video_fields(text: str) -> str:
    lines = text.splitlines(keepends=True)
    start, end = _function_bounds(lines, "update_kuaishou_video")

    liked_line = (
        f'        "liked_count": str(_ks_first_present((photo_info, video_item), '
        f'"realLikeCount", "likeCount", "liked_count", "like_count")),  # {MARKER}\n'
    )
    comment_line = (
        f'        "comment_count": str(_ks_first_present((photo_info, video_item), '
        f'"commentCount", "commentCountV2", "commentsCount", "comment_count")),  # {MARKER}\n'
    )

    liked_idx = None
    comment_idx = None
    view_idx = None
    for i in range(start, end):
        stripped = lines[i].lstrip()
        if stripped.startswith('"liked_count":'):
            liked_idx = i
        elif stripped.startswith('"comment_count":'):
            comment_idx = i
        elif stripped.startswith('"viewd_count":'):
            view_idx = i

    if liked_idx is None:
        raise RuntimeError("Kuaishou video liked_count field not found")
    lines[liked_idx] = liked_line

    # Recompute bounds after any line replacement; line count has not changed.
    if comment_idx is not None:
        lines[comment_idx] = comment_line
    else:
        if view_idx is None:
            raise RuntimeError("Kuaishou video viewd_count field not found")
        lines.insert(view_idx + 1, comment_line)

    return "".join(lines)


def _replace_or_insert_comment_like(text: str) -> str:
    lines = text.splitlines(keepends=True)
    start, end = _function_bounds(lines, "update_ks_video_comment")

    like_line = (
        f'        "like_count": str(_ks_first_present((comment_item,), '
        f'"like_count", "likeCount", "realLikeCount")),  # {MARKER}\n'
    )

    like_idx = None
    sub_idx = None
    for i in range(start, end):
        stripped = lines[i].lstrip()
        if stripped.startswith('"like_count":'):
            like_idx = i
        elif stripped.startswith('"sub_comment_count":'):
            sub_idx = i

    if like_idx is not None:
        lines[like_idx] = like_line
    else:
        if sub_idx is None:
            raise RuntimeError("Kuaishou comment sub_comment_count field not found")
        lines.insert(sub_idx + 1, like_line)

    return "".join(lines)




def _patch_core_detail_comment_count(root: Path) -> None:
    path = root / "media_platform" / "kuaishou" / "core.py"
    if not path.exists():
        raise RuntimeError(f"Kuaishou core file not found: {path}")
    text = _read(path)
    marker = "PROMOTION_WEEK_KS_DETAIL_COMMENT_COUNT_V1"
    if marker in text:
        ast.parse(text, filename=str(path))
        return

    lines = text.splitlines(keepends=True)
    func_start = -1
    func_end = len(lines)
    for idx, line in enumerate(lines):
        if line.lstrip().startswith("async def get_video_info_task("):
            func_start = idx
            base_indent = len(line) - len(line.lstrip())
            for j in range(idx + 1, len(lines)):
                stripped = lines[j].lstrip()
                indent = len(lines[j]) - len(stripped)
                if stripped and indent <= base_indent and (
                    stripped.startswith("async def ")
                    or stripped.startswith("def ")
                    or stripped.startswith("class ")
                ):
                    func_end = j
                    break
            break
    if func_start < 0:
        raise RuntimeError("Kuaishou get_video_info_task not found")

    author_idx = -1
    author_indent = ""
    seen_detail = False
    for idx in range(func_start, func_end):
        stripped = lines[idx].strip()
        if stripped.startswith('detail = result.get("visionVideoDetail")'):
            seen_detail = True
            continue
        if seen_detail and stripped.startswith('author = detail.get("author", {})'):
            author_idx = idx
            author_indent = lines[idx][: len(lines[idx]) - len(lines[idx].lstrip())]
            break

    if author_idx < 0:
        raise RuntimeError("Kuaishou detail comment-count anchor not found")

    i = author_indent
    i1 = i + "    "
    i2 = i + "        "
    i3 = i + "            "
    insertion = (
        f'{i}# {marker}:\n'
        f'{i}# Fetch the platform-displayed public comment total before persisting\n'
        f'{i}# the detail row. Missing remains missing; a real zero remains zero.\n'
        f'{i}if all(\n'
        f'{i1}photo.get(key) in (None, "")\n'
        f'{i1}for key in ("commentCount", "commentCountV2", "commentsCount", "comment_count")\n'
        f'{i}):\n'
        f'{i1}try:\n'
        f'{i2}_ks_comment_summary = await self.ks_client.get_video_comments(video_id, "")\n'
        f'{i2}_ks_public_count = (\n'
        f'{i3}_ks_comment_summary.get("commentCountV2")\n'
        f'{i3}if isinstance(_ks_comment_summary, dict)\n'
        f'{i3}else None\n'
        f'{i2})\n'
        f'{i2}if _ks_public_count in (None, "") and isinstance(_ks_comment_summary, dict):\n'
        f'{i3}_ks_public_count = _ks_comment_summary.get("commentCount")\n'
        f'{i2}if _ks_public_count not in (None, ""):\n'
        f'{i3}photo["commentCount"] = _ks_public_count\n'
        f'{i3}utils.logger.info(\n'
        f'{i3}    f"[KS_DETAIL_COMMENT_COUNT] video={{video_id}} count={{_ks_public_count}}"\n'
        f'{i3})\n'
        f'{i1}except Exception as _ks_count_exc:\n'
        f'{i2}utils.logger.warning(\n'
        f'{i2}    f"[KS_DETAIL_COMMENT_COUNT] video={{video_id}} unavailable: "\n'
        f'{i2}    f"{{type(_ks_count_exc).__name__}}: {{_ks_count_exc}}"\n'
        f'{i2})\n'
    )
    lines.insert(author_idx + 1, insertion)
    _write(path, "".join(lines))

def patch_store(root: Path) -> None:
    path = root / "store" / "kuaishou" / "__init__.py"
    if not path.exists():
        raise RuntimeError(f"Kuaishou store file not found: {path}")

    text = _read(path)
    text = _ensure_first_present_helper(text)
    text = _replace_or_insert_video_fields(text)
    text = _replace_or_insert_comment_like(text)
    _write(path, text)


def check(root: Path) -> dict:
    path = root / "store" / "kuaishou" / "__init__.py"
    result = {
        "patch_version": 1,
        "store_exists": path.exists(),
        "helper_present": False,
        "video_like_present": False,
        "video_comment_count_present": False,
        "comment_like_present": False,
        "missing_is_not_forced_to_zero": False,
        "detail_comment_count_enrichment_present": False,
        "ok": False,
    }
    if not path.exists():
        return result

    text = _read(path)
    try:
        ast.parse(text, filename=str(path))
        result["helper_present"] = "def _ks_first_present(" in text and MARKER in text
        result["video_like_present"] = (
            '"liked_count": str(_ks_first_present((photo_info, video_item), '
            '"realLikeCount", "likeCount", "liked_count", "like_count"))' in text
        )
        result["video_comment_count_present"] = (
            '"comment_count": str(_ks_first_present((photo_info, video_item), '
            '"commentCount", "commentCountV2", "commentsCount", "comment_count"))' in text
        )
        result["comment_like_present"] = (
            '"like_count": str(_ks_first_present((comment_item,), '
            '"like_count", "likeCount", "realLikeCount"))' in text
        )
        result["missing_is_not_forced_to_zero"] = (
            'def _ks_first_present(' in text
            and 'return ""' in text
        )
        result["ok"] = all([
            result["helper_present"],
            result["video_like_present"],
            result["video_comment_count_present"],
            result["comment_like_present"],
            result["missing_is_not_forced_to_zero"],
        ])
    except Exception:
        pass

    core = root / "media_platform" / "kuaishou" / "core.py"
    if core.exists():
        try:
            core_text = _read(core)
            ast.parse(core_text, filename=str(core))
            result["detail_comment_count_enrichment_present"] = (
                "PROMOTION_WEEK_KS_DETAIL_COMMENT_COUNT_V1" in core_text
                and "[KS_DETAIL_COMMENT_COUNT]" in core_text
            )
        except Exception:
            pass
    result["ok"] = bool(result["ok"] and result["detail_comment_count_enrichment_present"])
    result["purpose"] = (
        "persist_kuaishou_video_likes_platform_comment_count_and_comment_likes_"
        "without_conflating_missing_fields_with_real_zero"
    )
    return result


def apply(root: Path) -> dict:
    patch_store(root)
    _patch_core_detail_comment_count(root)
    return check(root)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Patch pinned MediaCrawler Kuaishou storage so video likes, platform "
            "comment counts and comment likes survive raw -> JSONL -> export."
        )
    )
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    try:
        result = check(root) if args.check else apply(root)
    except Exception as exc:
        print(json.dumps(
            {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
            indent=2,
        ))
        return 2

    print(json.dumps({"root": str(root), **result}, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
