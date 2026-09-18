from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_TIEBA_PUBLIC_REGION_VERIFY_V1"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def patch_helper(root: Path) -> None:
    """Validate the shared Tieba region patch without rewriting its V4 markers.

    The shared patch is intentionally authoritative so repeated student upgrades
    remain idempotent. This platform-specific layer only verifies that all known
    public coarse-region sources are wired through model -> extractor -> JSONL.
    """
    path = root / "media_platform/tieba/help.py"
    ast.parse(read(path), filename=str(path))


def check(root: Path) -> dict:
    model = root / "model/m_baidu_tieba.py"
    helper = root / "media_platform/tieba/help.py"
    store = root / "store/tieba/__init__.py"
    result = {
        "patch_version": 1,
        "model_exists": model.exists(),
        "helper_exists": helper.exists(),
        "store_exists": store.exists(),
        "model_ip_location": False,
        "api_search_region": False,
        "api_note_region": False,
        "api_comment_region": False,
        "html_note_comment_region": False,
        "html_nested_region": False,
        "jsonl_persistence": False,
        "shared_patch_marker": False,
        "ok": False,
    }
    if not model.exists() or not helper.exists() or not store.exists():
        return result
    try:
        model_text = read(model)
        helper_text = read(helper)
        store_text = read(store)
        ast.parse(model_text, filename=str(model))
        ast.parse(helper_text, filename=str(helper))
        ast.parse(store_text, filename=str(store))

        result["model_ip_location"] = (
            'ip_location: str = Field(default="", description="Coarse public IP-location label")'
            in model_text
        )
        result["api_search_region"] = (
            'item.get("ip_address")' in helper_text
            and 'user.get("ip_address")' in helper_text
        )
        result["api_note_region"] = (
            'first_floor.get("ip_address")' in helper_text
            and 'author.get("ip_address")' in helper_text
        )
        result["api_comment_region"] = (
            'item.get("ip_address")' in helper_text
            and 'user.get("ip_address")' in helper_text
        )
        result["html_note_comment_region"] = (
            "extract_ip_and_pub_time(other_info_content)" in helper_text
            and "ip_location=coarse_public_region(ip_location)" in helper_text
        )
        result["html_nested_region"] = (
            'comment_value.get("ip_address")' in helper_text
            and 'comment_value.get("ip_region")' in helper_text
        )
        result["jsonl_persistence"] = (
            'save_note_item.pop("ip_location", None)' in store_text
            and 'save_comment_item.pop("ip_location", None)' in store_text
        )
        result["shared_patch_marker"] = "PROMOTION_WEEK_PUBLIC_REGION_PATCH_V4" in (
            model_text + helper_text + store_text
        )
        result["ok"] = all(result[k] for k in (
            "model_ip_location",
            "api_search_region",
            "api_note_region",
            "api_comment_region",
            "html_note_comment_region",
            "html_nested_region",
            "jsonl_persistence",
            "shared_patch_marker",
        ))
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify Tieba coarse public IP-region persistence.")
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    try:
        if not args.check:
            patch_helper(root)
        result = check(root)
    except Exception as exc:
        print(json.dumps({"ok": False, "root": str(root), "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({
        "root": str(root),
        **result,
        "marker": MARKER,
        "privacy": "coarse_public_region_only_no_real_ip_no_precise_location",
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
