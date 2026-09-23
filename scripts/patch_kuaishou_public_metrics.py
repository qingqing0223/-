from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


MARKER = "PROMOTION_WEEK_KS_PUBLIC_METRICS_V1"
ENABLED_VALUES = {"1", "true", "yes", "on"}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def _method_bounds(text: str, class_name: str, method_name: str) -> tuple[int, int, str]:
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                    start = offsets[child.lineno - 1]
                    end = offsets[child.end_lineno]
                    indent = lines[child.lineno - 1][: len(lines[child.lineno - 1]) - len(lines[child.lineno - 1].lstrip())]
                    return start, end, indent
    raise RuntimeError(f"{class_name}.{method_name} not found")


def _function_bounds(text: str, function_name: str) -> tuple[int, int]:
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return offsets[node.lineno - 1], offsets[node.end_lineno]
    raise RuntimeError(f"{function_name} not found")


def _core_methods(indent: str) -> str:
    i1, i2, i3, i4 = indent, indent + "    ", indent + "        ", indent + "            "
    return (
        f"{i1}async def _enrich_public_profile_metrics(self, video_item: Dict) -> Dict:\n"
        f"{i2}\"\"\"Attach public follower/following counters without persisting raw account IDs.\"\"\"\n"
        f"{i2}# {MARKER}\n"
        f"{i2}if str(os.getenv(\"KUAISHOU_PUBLIC_METRICS\", \"\")).strip().lower() not in {{\"1\", \"true\", \"yes\", \"on\"}}:\n"
        f"{i3}return video_item\n"
        f"{i2}if not isinstance(video_item, dict):\n"
        f"{i3}return video_item\n"
        f"{i2}author = video_item.get(\"author\") or {{}}\n"
        f"{i2}if not isinstance(author, dict):\n"
        f"{i3}return video_item\n"
        f"{i2}author_id = str(author.get(\"id\") or author.get(\"user_id\") or author.get(\"userId\") or \"\").strip()\n"
        f"{i2}if not author_id:\n"
        f"{i3}return video_item\n"
        f"{i2}cache = getattr(self, \"_promotion_week_public_profile_metrics_cache\", None)\n"
        f"{i2}if cache is None:\n"
        f"{i3}cache = {{}}\n"
        f"{i3}self._promotion_week_public_profile_metrics_cache = cache\n"
        f"{i2}if author_id not in cache:\n"
        f"{i3}metrics = {{\"follower_count\": None, \"following_count\": None}}\n"
        f"{i3}try:\n"
        f"{i4}profile = await self.ks_client.get_creator_info(author_id)\n"
        f"{i4}owner_count = profile.get(\"ownerCount\", {{}}) if isinstance(profile, dict) else {{}}\n"
        f"{i4}if isinstance(owner_count, dict):\n"
        f"{i4}    metrics[\"follower_count\"] = owner_count.get(\"fan\")\n"
        f"{i4}    metrics[\"following_count\"] = owner_count.get(\"follow\")\n"
        f"{i3}except Exception as exc:\n"
        f"{i4}utils.logger.warning(\n"
        f"{i4}    f\"[KS_PUBLIC_PROFILE_METRICS] profile counter fetch failed: {{type(exc).__name__}}\"\n"
        f"{i4})\n"
        f"{i3}cache[author_id] = metrics\n"
        f"{i2}metrics = cache[author_id]\n"
        f"{i2}follower_count = metrics.get(\"follower_count\")\n"
        f"{i2}following_count = metrics.get(\"following_count\")\n"
        f"{i2}if follower_count is not None:\n"
        f"{i3}author[\"follower_count\"] = follower_count\n"
        f"{i3}author[\"fans_count\"] = follower_count\n"
        f"{i2}if following_count is not None:\n"
        f"{i3}author[\"following_count\"] = following_count\n"
        f"{i3}author[\"follow_count\"] = following_count\n"
        f"{i2}video_item[\"author\"] = author\n"
        f"{i2}return video_item\n"
    )


def _insert_after_matching_line(text: str, *, contains: str, insertion: str, after_contains: str | None = None) -> str:
    """Insert one line using the indentation of the matched source line.

    MediaCrawler has changed indentation/nesting in the Kuaishou search loop
    across revisions.  The patch should follow the code shape instead of
    requiring one exact whitespace layout.
    """
    lines = text.splitlines(keepends=True)
    for idx, line in enumerate(lines):
        if contains not in line:
            continue
        target_idx = idx
        if after_contains is not None:
            base_indent = len(line) - len(line.lstrip())
            for j in range(idx + 1, len(lines)):
                candidate = lines[j]
                if candidate.strip():
                    indent = len(candidate) - len(candidate.lstrip())
                    if indent <= base_indent:
                        break
                if after_contains in candidate:
                    target_idx = j
                    break
            else:
                continue
            if target_idx == idx:
                continue
        indent_text = lines[target_idx][: len(lines[target_idx]) - len(lines[target_idx].lstrip())]
        lines.insert(target_idx + 1, indent_text + insertion + "\n")
        return "".join(lines)
    raise RuntimeError(f"Kuaishou patch anchor not found: {contains}")


def _insert_before_return_in_method(text: str, class_name: str, method_name: str, return_expr: str, insertion: str) -> str:
    start, end, _ = _method_bounds(text, class_name, method_name)
    segment = text[start:end]
    lines = segment.splitlines(keepends=True)
    for idx, line in enumerate(lines):
        if line.strip() == return_expr:
            indent_text = line[: len(line) - len(line.lstrip())]
            lines.insert(idx, indent_text + insertion + "\n")
            return text[:start] + "".join(lines) + text[end:]
    raise RuntimeError(f"{class_name}.{method_name}: return anchor not found: {return_expr}")


def _patch_core(text: str) -> str:
    if MARKER not in text:
        start, _, indent = _method_bounds(text, "KuaishouCrawler", "get_video_info_task")
        text = text[:start] + _core_methods(indent) + "\n" + text[start:]

    search_marker = "await self._enrich_public_profile_metrics(video_detail)"
    if search_marker not in text:
        try:
            text = _insert_after_matching_line(
                text,
                contains='for video_detail in videos_res.get("feeds", [])',
                after_contains="video_id_list.append(",
                insertion=search_marker,
            )
        except RuntimeError:
            # The realtime-slice patch rewrites the upstream loop to iterate
            # over _ks_feeds.  Public-metric enrichment must compose with that
            # idempotent patch order as well.
            text = _insert_after_matching_line(
                text,
                contains="for video_detail in _ks_feeds:",
                after_contains="video_id_list.append(",
                insertion=search_marker,
            )

    detail_marker = "await self._enrich_public_profile_metrics(detail)"
    if detail_marker not in text:
        text = _insert_before_return_in_method(
            text,
            "KuaishouCrawler",
            "get_video_info_task",
            "return detail",
            detail_marker,
        )
    return text


def _inject_before_logger(segment: str, injection: str, function_name: str) -> str:
    if MARKER in segment:
        return segment
    needle = "    utils.logger.info("
    pos = segment.find(needle)
    if pos < 0:
        raise RuntimeError(f"{function_name}: logger anchor not found")
    return segment[:pos] + injection + segment[pos:]


def _patch_store(text: str) -> str:
    if "import os\n" not in text:
        text = text.replace("from typing import List\n", "from typing import List\n\nimport os\n", 1)

    video_start, video_end = _function_bounds(text, "update_kuaishou_video")
    video = text[video_start:video_end]
    video_injection = (
        f'    # {MARKER}: keep only public aggregate creator counters in JSONL output\n'
        '    if str(os.getenv("KUAISHOU_PUBLIC_METRICS", "")).strip().lower() in {"1", "true", "yes", "on"} '
        'and str(getattr(config, "SAVE_DATA_OPTION", "")).lower() == "jsonl":\n'
        '        follower_count = user_info.get("follower_count")\n'
        '        if follower_count is None:\n'
        '            follower_count = user_info.get("fans_count")\n'
        '        following_count = user_info.get("following_count")\n'
        '        if following_count is None:\n'
        '            following_count = user_info.get("follow_count")\n'
        '        if follower_count is not None and follower_count != "":\n'
        '            save_content_item["follower_count"] = follower_count\n'
        '        if following_count is not None and following_count != "":\n'
        '            save_content_item["following_count"] = following_count\n'
    )
    patched_video = _inject_before_logger(video, video_injection, "update_kuaishou_video")
    text = text[:video_start] + patched_video + text[video_end:]

    comment_start, comment_end = _function_bounds(text, "update_ks_video_comment")
    comment = text[comment_start:comment_end]
    comment_injection = (
        f'    # {MARKER}: preserve the public comment-like counter already returned by the API\n'
        '    if str(os.getenv("KUAISHOU_PUBLIC_METRICS", "")).strip().lower() in {"1", "true", "yes", "on"} '
        'and str(getattr(config, "SAVE_DATA_OPTION", "")).lower() == "jsonl":\n'
        '        public_like_count = None\n'
        '        for key in ("realLikedCount", "likedCount", "likeCount", "like_count", "liked_count", "real_liked_count"):\n'
        '            value = comment_item.get(key)\n'
        '            if value is not None and value != "":\n'
        '                public_like_count = value\n'
        '                break\n'
        '        if public_like_count is not None:\n'
        '            save_comment_item["like_count"] = str(public_like_count)\n'
    )
    patched_comment = _inject_before_logger(comment, comment_injection, "update_ks_video_comment")
    text = text[:comment_start] + patched_comment + text[comment_end:]
    return text


def patch(root: Path) -> None:
    core = root / "media_platform/kuaishou/core.py"
    store = root / "store/kuaishou/__init__.py"
    _write(core, _patch_core(_read(core)))
    _write(store, _patch_store(_read(store)))


def check(root: Path) -> dict:
    core_text = _read(root / "media_platform/kuaishou/core.py")
    store_text = _read(root / "store/kuaishou/__init__.py")
    result = {
        "core_marker": MARKER in core_text,
        "search_profile_enrichment": "await self._enrich_public_profile_metrics(video_detail)" in core_text,
        "detail_profile_enrichment": "await self._enrich_public_profile_metrics(detail)" in core_text,
        "profile_owner_count": 'owner_count.get("fan")' in core_text and 'owner_count.get("follow")' in core_text,
        "store_video_followers": 'save_content_item["follower_count"]' in store_text,
        "store_video_following": 'save_content_item["following_count"]' in store_text,
        "store_comment_likes": 'save_comment_item["like_count"]' in store_text,
        "jsonl_only": 'SAVE_DATA_OPTION' in store_text and '"jsonl"' in store_text,
    }
    result["ok"] = all(result.values())
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if not args.check:
        patch(root)
    result = {"root": str(root), **check(root)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
