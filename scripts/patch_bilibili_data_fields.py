from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_BILI_DATA_FIELDS_V1"


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


def patch_store(root: Path) -> None:
    path = root / "store" / "bilibili" / "__init__.py"
    text = read(path)

    if f"# {MARKER}: public publisher/video metadata" not in text:
        old = '''    video_item_view: Dict = video_item.get("View")
    video_user_info: Dict = video_item_view.get("owner")
    video_item_stat: Dict = video_item_view.get("stat")
    video_id = str(video_item_view.get("aid"))
'''
        new = f'''    video_item_view: Dict = video_item.get("View")
    video_user_info: Dict = video_item_view.get("owner")
    video_item_stat: Dict = video_item_view.get("stat")

    # {MARKER}: public publisher/video metadata already returned by view/detail.
    # No extra profile request is needed for these fields.
    _bili_card = video_item.get("Card") or {{}}
    _bili_card_info = _bili_card.get("card") or {{}}
    _bili_official = (
        _bili_card_info.get("Official")
        or _bili_card_info.get("official")
        or {{}}
    )
    _bili_tags = []
    for _tag in (video_item.get("Tags") or []):
        if isinstance(_tag, dict):
            _name = _tag.get("tag_name") or _tag.get("name")
            if _name:
                _bili_tags.append(str(_name))
        elif _tag:
            _bili_tags.append(str(_tag))

    video_id = str(video_item_view.get("aid"))
'''
        text = replace_once(
            text,
            old,
            new,
            "Bilibili public publisher/video metadata setup",
        )

    if f'"data_fields_version": "{MARKER}"' not in text:
        old = '''        "video_cover_url": video_item_view.get("pic", ""),
        "source_keyword": source_keyword_var.get(),
    }
'''
        new = f'''        "video_cover_url": video_item_view.get("pic", ""),
        "source_keyword": source_keyword_var.get(),

        # {MARKER}: fields needed by collection Tables 1-5.
        "bvid": str(video_item_view.get("bvid") or ""),
        "category_name": video_item_view.get("tname", ""),
        "duration": video_item_view.get("duration"),
        "tags": _bili_tags,

        # Exact public publisher metadata remains in the LOCAL raw JSONL. The
        # repository's normalized/public GitHub path continues to prefer the
        # anonymized creator_hash and masked nickname.
        "creator_public_id": str(video_user_info.get("mid") or ""),
        "account_name": video_user_info.get("name", ""),
        "creator_profile_url": (
            f"https://space.bilibili.com/{{video_user_info.get('mid')}}"
            if video_user_info.get("mid") not in (None, "")
            else ""
        ),
        "follower_count": (
            _bili_card_info.get("fans")
            if _bili_card_info.get("fans") not in (None, "")
            else _bili_card.get("follower")
        ),
        "following_count": (
            _bili_card_info.get("attention")
            if _bili_card_info.get("attention") not in (None, "")
            else _bili_card_info.get("friend")
        ),
        "creator_official_title": _bili_official.get("title", ""),
        "creator_official_type": _bili_official.get("type"),
        "data_fields_version": "{MARKER}",
    }}
'''
        text = replace_once(
            text,
            old,
            new,
            "Bilibili public publisher/video metadata persistence",
        )

    if '"root_comment_id": str(comment_item.get("root", 0)),' not in text:
        old = '''        "comment_id": comment_id,
        "parent_comment_id": parent_comment_id,
        "create_time": comment_item.get("ctime"),
'''
        new = '''        "comment_id": comment_id,
        "parent_comment_id": parent_comment_id,
        "root_comment_id": str(comment_item.get("root", 0)),
        "create_time": comment_item.get("ctime"),
'''
        text = replace_once(
            text,
            old,
            new,
            "Bilibili nested comment root persistence",
        )

    write_py(path, text)


def check(root: Path) -> dict:
    path = root / "store" / "bilibili" / "__init__.py"
    result = {
        "patch_version": 1,
        "store_exists": path.exists(),
        "publisher_metrics": False,
        "video_metadata": False,
        "root_hierarchy": False,
        "local_public_account_fields": False,
        "ok": False,
    }
    if not path.exists():
        return result

    try:
        text = read(path)
        ast.parse(text, filename=str(path))
        result["publisher_metrics"] = (
            '"follower_count":' in text
            and '"following_count":' in text
            and '"creator_official_title":' in text
        )
        result["video_metadata"] = (
            '"bvid":' in text
            and '"category_name":' in text
            and '"duration":' in text
            and '"tags": _bili_tags' in text
        )
        result["root_hierarchy"] = (
            '"root_comment_id": str(comment_item.get("root", 0))' in text
        )
        result["local_public_account_fields"] = (
            '"creator_public_id":' in text
            and '"account_name":' in text
            and '"creator_profile_url":' in text
            and '"creator_hash": anonymize_user_id' in text
        )
        result["ok"] = all([
            result["publisher_metrics"],
            result["video_metadata"],
            result["root_hierarchy"],
            result["local_public_account_fields"],
        ])
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Persist Bilibili public publisher/video fields and explicit "
            "parent/root comment hierarchy in local JSONL."
        )
    )
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    try:
        if not args.check:
            patch_store(root)
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
        "privacy": (
            "exact public account id/name/profile URL stay in local raw JSONL; "
            "public GitHub output remains aggregate/anonymized"
        ),
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
