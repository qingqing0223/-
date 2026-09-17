from __future__ import annotations

import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

import monitor.crawler_runner as crawler_runner
import run_single_platform
from scripts import patch_douyin_comment_hierarchy


CLIENT_FIXTURE = '''import asyncio\n\nclass DouYinClient:\n    async def get_aweme_all_comments(self):\n        result = []\n        comments_has_more = 1\n        comments_cursor = 0\n        while comments_has_more:\n            comments_res = {}\n            comments = comments_res.get("comments", [])\n            if not comments:\n                continue\n            result.extend(comments)\n            for comment in comments:\n                reply_comment_total = comment.get("reply_comment_total")\n                if reply_comment_total > 0:\n                    comment_id = comment.get("cid")\n                    sub_comments_has_more = 1\n                    while sub_comments_has_more:\n                        sub_comments_res = {}\n                        sub_comments = sub_comments_res.get("comments", [])\n                        if not sub_comments:\n                            continue\n                        result.extend(sub_comments)\n        return result\n'''

STORE_FIXTURE = '''async def update_dy_aweme_comment(aweme_id, comment_item):\n    comment_id = comment_item.get("cid")\n    parent_comment_id = comment_item.get("reply_id", "0")\n    save_comment_item = {\n        "comment_id": comment_id,\n        "parent_comment_id": parent_comment_id,\n    }\n    return save_comment_item\n'''


class DouyinHierarchyPatchTests(unittest.TestCase):
    def test_patch_is_idempotent_and_persists_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = root / "media_platform" / "douyin" / "client.py"
            store = root / "store" / "douyin" / "__init__.py"
            client.parent.mkdir(parents=True)
            store.parent.mkdir(parents=True)
            client.write_text(CLIENT_FIXTURE, encoding="utf-8")
            store.write_text(STORE_FIXTURE, encoding="utf-8")

            patch_douyin_comment_hierarchy.patch_client(root)
            patch_douyin_comment_hierarchy.patch_store(root)
            first_client = client.read_text(encoding="utf-8")
            first_store = store.read_text(encoding="utf-8")

            patch_douyin_comment_hierarchy.patch_client(root)
            patch_douyin_comment_hierarchy.patch_store(root)
            self.assertEqual(first_client, client.read_text(encoding="utf-8"))
            self.assertEqual(first_store, store.read_text(encoding="utf-8"))

            report = patch_douyin_comment_hierarchy.check(root)
            self.assertTrue(report["ok"], json.dumps(report))
            self.assertIn('root_comment_id', first_client)
            self.assertIn('root_comment_id', first_store)


class DouyinRealtimeIsolationTests(unittest.TestCase):
    def test_first_candidate_failure_does_not_abort_second(self):
        original_detail = crawler_runner._run_detail_comment_recovery
        original_marker = getattr(crawler_runner, "_promotion_week_dy_realtime_policy", None)
        if hasattr(crawler_runner, "_promotion_week_dy_realtime_policy"):
            delattr(crawler_runner, "_promotion_week_dy_realtime_policy")
        try:
            run_single_platform._install_douyin_realtime_policy()
            wrapped = crawler_runner._run_detail_comment_recovery
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(list(cmd))
                rc = 1 if len(calls) == 1 else 0
                return types.SimpleNamespace(returncode=rc)

            with tempfile.TemporaryDirectory() as tmp, mock.patch("run_single_platform.subprocess.run", side_effect=fake_run):
                root = Path(tmp)
                out = root / "stdout.log"
                err = root / "stderr.log"
                out.write_text("", encoding="utf-8")
                err.write_text("", encoding="utf-8")
                rc, attempts = wrapped(
                    {
                        "realtime_mode": True,
                        "douyin_realtime_detail_budget_seconds": 120,
                        "douyin_realtime_max_comments_per_video": 100,
                        "login_type": "qrcode",
                        "max_concurrency_num": 1,
                        "get_sub_comment": "yes",
                        "save_data_option": "jsonl",
                        "media_crawler_root": str(root),
                    },
                    "dy",
                    ["https://www.douyin.com/video/1", "https://www.douyin.com/video/2"],
                    root,
                    out,
                    err,
                    batch_size=1,
                )

            self.assertEqual(rc, 0)
            self.assertEqual(attempts, 2)
            self.assertEqual(len(calls), 2)
        finally:
            crawler_runner._run_detail_comment_recovery = original_detail
            if original_marker is None:
                if hasattr(crawler_runner, "_promotion_week_dy_realtime_policy"):
                    delattr(crawler_runner, "_promotion_week_dy_realtime_policy")
            else:
                crawler_runner._promotion_week_dy_realtime_policy = original_marker


if __name__ == "__main__":
    unittest.main()
