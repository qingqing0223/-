from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync_poms_dashboard.py"
SPEC = importlib.util.spec_from_file_location("sync_poms_dashboard", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class PomsDashboardCommentTests(unittest.TestCase):
    def test_raw_comment_tables_are_read_until_the_final_page(self):
        first_page = [{"id": value} for value in range(500)]
        second_page = [{"id": 500}]
        with patch.object(MODULE, "fetch_rows", side_effect=[first_page, second_page]) as mocked:
            rows = MODULE.fetch_paginated_rows("https://poms.example", "comment_basic_information", 20)

        self.assertEqual(len(rows), 501)
        self.assertEqual(
            [call.args[1] for call in mocked.call_args_list],
            [
                "comment_basic_information?page=1&page_size=500",
                "comment_basic_information?page=2&page_size=500",
            ],
        )

    def test_region_comment_snapshot_uses_content_account_region_without_identity(self):
        source = {name: [] for name in MODULE.TABLE_PATHS}
        source["platforms"] = [
            {
                "platform": "微博",
                "total_information_count": 1,
                "published_content_count": 1,
                "comment_and_reply_count": 1,
            }
        ]
        source["published_contents"] = [
            {
                "published_content_id": "post-001",
                "platform_name": "微博",
                "account_ip_location": "四川",
                "is_valid_monitoring_data": True,
            }
        ]
        source["comments"] = [
            {
                "corresponding_published_content_id": "post-001",
                "comment_id": "comment-001",
                "platform_name": "微博",
                "commenter_user_id": "must-not-be-published",
                "comment_text": "这是一条公开评论",
                "commented_at": "2026-10-03T11:15:00+08:00",
                "is_valid_comment": True,
            }
        ]

        snapshot = MODULE.build_snapshot(source)

        self.assertEqual(
            snapshot["regionComments"],
            [
                {
                    "region": "四川",
                    "province": "四川",
                    "platform": "微博",
                    "text": "这是一条公开评论",
                    "commentedAt": "2026-10-03T11:15:00+08:00",
                    "date": "2026-10-03",
                    "label": "公众评论",
                }
            ],
        )
        self.assertNotIn("commenter_user_id", snapshot["regionComments"][0])
        self.assertNotIn("comment_id", snapshot["regionComments"][0])


if __name__ == "__main__":
    unittest.main()
