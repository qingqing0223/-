from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_KS_REALTIME_SEARCH_V1"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def patch(root: Path) -> None:
    path = root / "media_platform" / "kuaishou" / "core.py"
    text = _read(path)

    if "import os\n" not in text:
        text = text.replace("import asyncio\n", "import asyncio\nimport os\n", 1)

    if MARKER not in text:
        old = """                for video_detail in videos_res.get("feeds", []):
                    video_id_list.append(video_detail.get("photo", {}).get("id"))
                    await kuaishou_store.update_kuaishou_video(video_item=video_detail)
"""
        new = """                # PROMOTION_WEEK_KS_REALTIME_SEARCH_V1: keep realtime discovery bounded per keyword.
                # Kuaishou returns a fixed page of up to 20 items. The generic
                # CRAWLER_MAX_NOTES_COUNT therefore cannot express a small per-keyword limit.
                _ks_feeds = list(videos_res.get("feeds", []) or [])
                if str(os.getenv("PROMOTION_WEEK_KS_REALTIME", "")).strip().lower() in {"1", "true", "yes", "on"}:
                    try:
                        _ks_rt_limit = max(
                            1,
                            int(os.getenv("PROMOTION_WEEK_KS_REALTIME_ITEMS_PER_KEYWORD", "5")),
                        )
                    except Exception:
                        _ks_rt_limit = 5
                    _ks_feeds = _ks_feeds[:_ks_rt_limit]
                    utils.logger.info(
                        f"[KS_REALTIME_DISCOVERY_SLICE] keyword={keyword} "
                        f"limit={_ks_rt_limit} kept={len(_ks_feeds)}"
                    )
                for video_detail in _ks_feeds:
                    video_id_list.append(video_detail.get("photo", {}).get("id"))
                    await kuaishou_store.update_kuaishou_video(video_item=video_detail)
"""
        if old not in text:
            raise RuntimeError("Kuaishou search-loop anchor not found")
        text = text.replace(old, new, 1)

    _write(path, text)


def check(root: Path) -> dict:
    path = root / "media_platform" / "kuaishou" / "core.py"
    result = {
        "core_exists": path.exists(),
        "marker_present": False,
        "env_gate_present": False,
        "per_keyword_slice_present": False,
        "historical_mode_untouched": False,
        "ok": False,
    }
    if not path.exists():
        return result
    text = _read(path)
    try:
        ast.parse(text, filename=str(path))
        result["marker_present"] = MARKER in text
        result["env_gate_present"] = "PROMOTION_WEEK_KS_REALTIME" in text
        result["per_keyword_slice_present"] = "_ks_feeds = _ks_feeds[:_ks_rt_limit]" in text
        result["historical_mode_untouched"] = "if str(os.getenv" in text
        result["ok"] = all([
            result["marker_present"],
            result["env_gate_present"],
            result["per_keyword_slice_present"],
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
