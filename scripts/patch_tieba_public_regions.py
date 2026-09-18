from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_TIEBA_PUBLIC_REGION_V1"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_py(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def patch_helper(root: Path) -> None:
    path = root / "media_platform/tieba/help.py"
    text = read(path)

    old_import = "from tools.public_region import coarse_public_region  # PROMOTION_WEEK_PUBLIC_REGION_PATCH_V4\n"
    new_import = f"from tools.public_region import coarse_public_region, first_coarse_public_region  # {MARKER}\n"
    if old_import in text:
        text = text.replace(old_import, new_import, 1)
    elif "from tools.public_region import coarse_public_region, first_coarse_public_region" not in text:
        fallback = "from tools.user_hash import anonymize_user_id, mask_nickname\n"
        if fallback not in text:
            raise RuntimeError("Tieba public-region import anchor not found")
        text = text.replace(fallback, fallback + new_import, 1)

    replacements = {
        'ip_location=coarse_public_region(item.get("ip_address") or item.get("ip_location") or item.get("ip_region") or user.get("ip_address") or user.get("ip_location") or user.get("ip_region")),':
        'ip_location=first_coarse_public_region(item.get("ip_address"), item.get("ip_location"), item.get("ip_region"), user.get("ip_address"), user.get("ip_location"), user.get("ip_region")),',
        'ip_location=coarse_public_region(first_floor.get("ip_address") or first_floor.get("ip_location") or first_floor.get("ip_region") or thread.get("ip_address") or thread.get("ip_location") or thread.get("ip_region") or author.get("ip_address") or author.get("ip_location") or author.get("ip_region")),':
        'ip_location=first_coarse_public_region(first_floor.get("ip_address"), first_floor.get("ip_location"), first_floor.get("ip_region"), thread.get("ip_address"), thread.get("ip_location"), thread.get("ip_region"), author.get("ip_address"), author.get("ip_location"), author.get("ip_region")),',
        'ip_location=coarse_public_region(comment_value.get("ip_address") or comment_value.get("ip_location") or comment_value.get("ip_region") or comment_value.get("region")),':
        'ip_location=first_coarse_public_region(comment_value.get("ip_address"), comment_value.get("ip_location"), comment_value.get("ip_region"), comment_value.get("region")),',
    }
    for old, new in replacements.items():
        if old in text:
            text = text.replace(old, new)

    write_py(path, text)


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
        "first_valid_region_helper": False,
        "api_note_region": False,
        "api_comment_region": False,
        "html_region": False,
        "jsonl_persistence": False,
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
        result["model_ip_location"] = 'ip_location: str = Field(default="", description="Coarse public IP-location label")' in model_text
        result["first_valid_region_helper"] = "first_coarse_public_region" in helper_text
        result["api_note_region"] = (
            'first_floor.get("ip_address")' in helper_text
            and 'author.get("ip_address")' in helper_text
        )
        result["api_comment_region"] = (
            'item.get("ip_address")' in helper_text
            and 'user.get("ip_address")' in helper_text
        )
        result["html_region"] = (
            "extract_ip_and_pub_time" in helper_text
            and 'comment_value.get("ip_address")' in helper_text
        )
        result["jsonl_persistence"] = (
            'save_note_item.pop("ip_location", None)' in store_text
            and 'save_comment_item.pop("ip_location", None)' in store_text
        )
        result["ok"] = all(result[k] for k in (
            "model_ip_location",
            "first_valid_region_helper",
            "api_note_region",
            "api_comment_region",
            "html_region",
            "jsonl_persistence",
        ))
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify and strengthen Tieba coarse public IP-region persistence.")
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
    print(json.dumps({"root": str(root), **result, "privacy": "coarse_public_region_only_no_real_ip_no_precise_location"}, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
