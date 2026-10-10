from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


MARKER = "PROMOTION_WEEK_WB_PUBLIC_IDENTITY_V1"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_py(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def _replace_top_level_async(
    text: str,
    function_name: str,
    replacement: str,
) -> str:
    tree = ast.parse(text)

    node = next(
        (
            item
            for item in tree.body
            if isinstance(item, ast.AsyncFunctionDef)
            and item.name == function_name
        ),
        None,
    )

    if node is None or node.end_lineno is None:
        raise RuntimeError(
            f"async function not found: {function_name}"
        )

    lines = text.splitlines(keepends=True)

    lines[
        node.lineno - 1 : node.end_lineno
    ] = [
        replacement.rstrip() + "\n"
    ]

    return "".join(lines)


def _replace_async_method(
    text: str,
    class_name: str,
    method_name: str,
    replacement: str,
) -> str:
    tree = ast.parse(text)

    cls = next(
        (
            item
            for item in tree.body
            if isinstance(item, ast.ClassDef)
            and item.name == class_name
        ),
        None,
    )

    if cls is None:
        raise RuntimeError(
            f"class not found: {class_name}"
        )

    method = next(
        (
            item
            for item in cls.body
            if isinstance(item, ast.AsyncFunctionDef)
            and item.name == method_name
        ),
        None,
    )

    if method is None or method.end_lineno is None:
        raise RuntimeError(
            f"method not found: "
            f"{class_name}.{method_name}"
        )

    lines = text.splitlines(keepends=True)

    lines[
        method.lineno - 1 : method.end_lineno
    ] = [
        replacement.rstrip() + "\n"
    ]

    return "".join(lines)


def _top_level_async_text(
    text: str,
    function_name: str,
) -> str:
    tree = ast.parse(text)

    node = next(
        (
            item
            for item in tree.body
            if isinstance(item, ast.AsyncFunctionDef)
            and item.name == function_name
        ),
        None,
    )

    if node is None or node.end_lineno is None:
        return ""

    lines = text.splitlines()

    return "\n".join(
        lines[
            node.lineno - 1 : node.end_lineno
        ]
    )


def _async_method_text(
    text: str,
    class_name: str,
    method_name: str,
) -> str:
    tree = ast.parse(text)

    cls = next(
        (
            item
            for item in tree.body
            if isinstance(item, ast.ClassDef)
            and item.name == class_name
        ),
        None,
    )

    if cls is None:
        return ""

    method = next(
        (
            item
            for item in cls.body
            if isinstance(item, ast.AsyncFunctionDef)
            and item.name == method_name
        ),
        None,
    )

    if method is None or method.end_lineno is None:
        return ""

    lines = text.splitlines()

    return "\n".join(
        lines[
            method.lineno - 1 : method.end_lineno
        ]
    )


def patch_store(root: Path) -> None:
    path = root / "store/weibo/__init__.py"
    text = read(path)

    text = text.replace(
        (
            "from tools.user_hash import "
            "anonymize_user_id, mask_nickname"
        ),
        (
            "from tools.user_hash import "
            "anonymize_user_id"
        ),
    )

    masked_nickname = (
        '        "nickname": '
        'mask_nickname('
        'user_info.get("screen_name", "")),\n'
    )

    public_identity = (
        '        "user_id": '
        'str(user_info.get("id") or "").strip(),\n'
        '        "nickname": '
        'str(user_info.get("screen_name") or "").strip(),\n'
    )

    masked_count = text.count(
        masked_nickname
    )

    if masked_count:
        if masked_count != 2:
            raise RuntimeError(
                "expected two Weibo masked nickname "
                f"anchors, found {masked_count}"
            )

        text = text.replace(
            masked_nickname,
            public_identity,
        )

    public_id_anchor = (
        '"user_id": '
        'str(user_info.get("id") or "").strip(),'
    )

    if text.count(public_id_anchor) < 2:
        raise RuntimeError(
            "public Weibo user_id persistence "
            "was not installed"
        )

    if '"original_or_repost": (' not in text:
        anchor = (
            '        "source_keyword": '
            'source_keyword_var.get(),\n'
        )

        if text.count(anchor) != 1:
            raise RuntimeError(
                "original/repost insertion anchor "
                "not found exactly once"
            )

        block = (
            anchor
            + "\n"
            + "        # "
            + MARKER
            + ": platform-provided "
              "original/repost evidence.\n"
            + '        "original_or_repost": (\n'
            + '            "\\u8f6c\\u8f7d"\n'
            + '            if isinstance('
              'mblog.get("retweeted_status"), dict)\n'
            + '            else "\\u539f\\u521b"\n'
            + '        ),\n'
        )

        text = text.replace(
            anchor,
            block,
            1,
        )

    creator_text = _top_level_async_text(
        text,
        "save_creator",
    )

    creator_ready = all(
        token in creator_text
        for token in (
            '"account_id": account_id',
            '"account_name": account_name',
            '"profile_url"',
            '"followers"',
            '"following"',
            "store_creator(",
        )
    )

    if not creator_ready:
        creator_replacement = '''
async def save_creator(
    user_id: str,
    user_info: Dict,
):
    """Persist public Weibo account data required by Tech Design V3."""
    if not user_info:
        return

    account_id = str(
        user_info.get("id")
        or user_id
        or ""
    ).strip()

    account_name = str(
        user_info.get("screen_name")
        or ""
    ).strip()

    if not account_id and not account_name:
        return

    creator_item = {
        "account_id": account_id,
        "account_name": account_name,
        "profile_url": str(
            user_info.get("profile_url")
            or ""
        ).strip(),
        "followers": user_info.get(
            "followers_count"
        ),
        "following": user_info.get(
            "follow_count"
        ),
        "region": "",
        "verified": user_info.get(
            "verified"
        ),
        "verified_type": user_info.get(
            "verified_type"
        ),
        "verified_reason": str(
            user_info.get("verified_reason")
            or ""
        ).strip(),
        "last_modify_ts": (
            utils.get_current_timestamp()
        ),
    }

    await WeibostoreFactory.create_store().store_creator(
        creator_item
    )
'''

        text = _replace_top_level_async(
            text,
            "save_creator",
            creator_replacement,
        )

    write_py(path, text)


def patch_store_impl(root: Path) -> None:
    path = root / "store/weibo/_store_impl.py"
    text = read(path)

    method_text = _async_method_text(
        text,
        "WeiboJsonlStoreImplement",
        "store_creator",
    )

    if not method_text:
        raise RuntimeError(
            "Weibo JSONL store_creator method "
            "was not found"
        )

    if 'item_type="account_info"' not in method_text:
        replacement = '''
    async def store_creator(
        self,
        creator: Dict,
    ):
        await self.writer.write_to_jsonl(
            item_type="account_info",
            item=creator,
        )
'''

        text = _replace_async_method(
            text,
            "WeiboJsonlStoreImplement",
            "store_creator",
            replacement,
        )

    write_py(path, text)


def check(root: Path) -> dict:
    store = root / "store/weibo/__init__.py"
    impl = root / "store/weibo/_store_impl.py"

    result = {
        "patch_version": 1,
        "store_exists": store.exists(),
        "store_impl_exists": impl.exists(),
        "public_user_id": False,
        "full_public_nickname": False,
        "masked_nickname_removed": False,
        "original_or_repost": False,
        "creator_public_profile": False,
        "creator_jsonl_persistence": False,
        "ok": False,
    }

    if not store.exists() or not impl.exists():
        return result

    try:
        store_text = read(store)
        impl_text = read(impl)

        ast.parse(
            store_text,
            filename=str(store),
        )
        ast.parse(
            impl_text,
            filename=str(impl),
        )

        result["public_user_id"] = (
            store_text.count(
                '"user_id": '
                'str(user_info.get("id") or "").strip(),'
            )
            >= 2
        )

        result["full_public_nickname"] = (
            store_text.count(
                '"nickname": '
                'str(user_info.get("screen_name") or "").strip(),'
            )
            >= 2
        )

        result["masked_nickname_removed"] = (
            "mask_nickname(" not in store_text
        )

        result["original_or_repost"] = (
            '"original_or_repost"' in store_text
            and 'mblog.get("retweeted_status")'
            in store_text
        )

        creator_text = _top_level_async_text(
            store_text,
            "save_creator",
        )

        result["creator_public_profile"] = all(
            token in creator_text
            for token in (
                '"account_id"',
                '"account_name"',
                '"profile_url"',
                '"followers"',
                '"following"',
                "store_creator(",
            )
        )

        method_text = _async_method_text(
            impl_text,
            "WeiboJsonlStoreImplement",
            "store_creator",
        )

        result["creator_jsonl_persistence"] = (
            'item_type="account_info"'
            in method_text
        )

        result["ok"] = all((
            result["public_user_id"],
            result["full_public_nickname"],
            result["masked_nickname_removed"],
            result["original_or_repost"],
            result["creator_public_profile"],
            result["creator_jsonl_persistence"],
        ))

    except Exception:
        pass

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Install/check public Weibo identity, "
            "originality and Table 5 profile persistence."
        )
    )

    parser.add_argument(
        "--root",
        required=True,
    )

    parser.add_argument(
        "--check",
        action="store_true",
    )

    args = parser.parse_args()
    root = Path(args.root).resolve()

    try:
        if not args.check:
            patch_store(root)
            patch_store_impl(root)

        result = check(root)

    except Exception as exc:
        print(json.dumps(
            {
                "ok": False,
                "root": str(root),
                "error": (
                    f"{type(exc).__name__}: {exc}"
                ),
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 2

    print(json.dumps(
        {
            "root": str(root),
            **result,
        },
        ensure_ascii=False,
        indent=2,
    ))

    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())