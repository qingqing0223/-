from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]

SCRIPT = (
    ROOT
    / "scripts"
    / "patch_weibo_public_identity.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location(
        "patch_weibo_public_identity",
        SCRIPT,
    )

    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(
        spec
    )

    spec.loader.exec_module(module)

    return module


class WeiboPublicIdentityPatchTest(
    unittest.TestCase
):
    def test_script_contract(self):
        text = SCRIPT.read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "PROMOTION_WEEK_WB_PUBLIC_IDENTITY_V1",
            text,
        )

        self.assertIn(
            "retweeted_status",
            text,
        )

        self.assertIn(
            'item_type="account_info"',
            text,
        )

        self.assertIn(
            "public_user_id",
            text,
        )

    def test_patch_is_idempotent(self):
        module = load_module()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            store = (
                root
                / "store"
                / "weibo"
                / "__init__.py"
            )

            impl = (
                root
                / "store"
                / "weibo"
                / "_store_impl.py"
            )

            store.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            store.write_text(
                '''
from typing import Dict
from tools.user_hash import anonymize_user_id, mask_nickname


async def update_weibo_note(note_item: Dict):
    mblog = {}
    user_info = mblog.get("user") or {}
    save_content_item = {
        "creator_hash": anonymize_user_id(user_info.get("id")),
        "nickname": mask_nickname(user_info.get("screen_name", "")),
        "source_keyword": source_keyword_var.get(),
    }


async def update_weibo_note_comment(note_id: str, comment_item: Dict):
    user_info = comment_item.get("user") or {}
    save_comment_item = {
        "creator_hash": anonymize_user_id(user_info.get("id")),
        "nickname": mask_nickname(user_info.get("screen_name", "")),
    }


async def save_creator(user_id: str, user_info: Dict):
    return
'''.lstrip(),
                encoding="utf-8",
            )

            impl.write_text(
                '''
from typing import Dict


class WeiboJsonlStoreImplement:
    async def store_creator(self, creator: Dict):
        pass


class WeiboSqliteStoreImplement:
    pass
'''.lstrip(),
                encoding="utf-8",
            )

            module.patch_store(root)
            module.patch_store_impl(root)

            first_store = store.read_text(
                encoding="utf-8"
            )

            first_impl = impl.read_text(
                encoding="utf-8"
            )

            result = module.check(root)

            self.assertTrue(
                result["ok"],
                result,
            )

            module.patch_store(root)
            module.patch_store_impl(root)

            self.assertEqual(
                first_store,
                store.read_text(
                    encoding="utf-8"
                ),
            )

            self.assertEqual(
                first_impl,
                impl.read_text(
                    encoding="utf-8"
                ),
            )


if __name__ == "__main__":
    unittest.main()