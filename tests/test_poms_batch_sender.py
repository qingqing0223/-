from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from monitor.poms_batch_sender import (
    TABLE12_GROUP,
    TABLE345_GROUP,
    TABLE_ENDPOINTS,
    build_poms_record,
    deliver_with_outbox,
)


class PomsBatchSenderTests(unittest.TestCase):

    def test_exact_field_order_matches_server_batch_samples(self):
        table1 = build_poms_record("table1", {
            "content_id": "p1",
            "platform": "微博",
            "author_id": "u1",
            "author_name": "账号",
            "author_ip_location": "",
            "account_type": "",
            "content_type": "post",
            "title": "",
            "content_text": "正文",
            "publish_time": "2026-09-21T09:00:00+08:00",
            "collection_time": "2026-09-21T09:05:00+08:00",
            "original_url": "https://m.weibo.cn/detail/p1",
            "matched_keywords": ["关键词"],
            "original_or_repost": "原创",
            "is_valid_monitoring_data": True,
            "invalid_reason": "",
        })
        self.assertEqual(list(table1), [
            "published_content_id",
            "platform_name",
            "publisher_account_id",
            "account_name",
            "account_ip_location",
            "account_type",
            "content_type",
            "title",
            "body_text_or_video_description",
            "published_at",
            "collected_at",
            "original_content_url",
            "matched_keywords",
            "originality_status",
            "is_valid_monitoring_data",
            "invalid_reason",
        ])
        self.assertIsNone(table1["account_ip_location"])
        self.assertIsNone(table1["account_type"])
        self.assertIsNone(table1["invalid_reason"])
        self.assertEqual(table1["content_type"], "图文")

        table2 = build_poms_record("table2", {
            "content_id": "p1",
            "comment_id": "c1",
            "platform": "微博",
            "comment_user_id": "cu1",
            "comment_user_ip_location": "",
            "comment_text": "评论",
            "comment_publish_time": "2026-09-21T09:01:00+08:00",
            "is_valid_comment": True,
        })
        self.assertEqual(list(table2), [
            "corresponding_published_content_id",
            "comment_id",
            "platform_name",
            "commenter_user_id",
            "commenter_ip_location",
            "comment_text",
            "commented_at",
            "is_valid_comment",
        ])

        table3 = build_poms_record("table3", {
            "content_id": "p1",
            "platform": "微博",
            "snapshot_time": "2026-09-21T10:00:00+08:00",
            "view_count": "",
            "like_count": 2,
            "comment_count": 3,
            "repost_count": 4,
            "share_count": "",
            "favorite_count": "",
        })
        self.assertEqual(list(table3), [
            "corresponding_published_content_id",
            "platform_name",
            "statistical_time",
            "view_or_play_count",
            "like_count",
            "comment_count",
            "repost_count",
            "share_count",
            "favorite_count",
        ])
        self.assertEqual(table3["view_or_play_count"], 0)
        self.assertEqual(table3["share_count"], 0)
        self.assertEqual(table3["favorite_count"], 0)

        table4 = build_poms_record("table4", {
            "content_id": "p1",
            "comment_id": "c1",
            "platform": "微博",
            "snapshot_time": "2026-09-21T10:00:00+08:00",
            "comment_reply_count": "",
            "comment_like_count": 5,
        })
        self.assertEqual(list(table4), [
            "corresponding_published_content_id",
            "comment_id",
            "platform_name",
            "statistical_time",
            "comment_reply_count",
            "comment_like_count",
        ])
        self.assertEqual(table4["comment_reply_count"], 0)

        table5 = build_poms_record("table5", {
            "account_id": "u1",
            "platform": "微博",
            "account_name": "账号",
            "profile_url": "",
            "account_type": "",
            "followers": "",
            "following": "",
            "region": "",
            "organization": "",
            "is_key_account": False,
            "related_post_count": 1,
            "views": "",
            "likes": 2,
            "comments": 3,
            "shares": 4,
            "favorites": "",
            "total_interactions": 9,
            "collected_at": "2026-09-21T10:00:00+08:00",
        })
        self.assertEqual(list(table5), [
            "account_id",
            "platform",
            "account_name",
            "homepage_url",
            "account_type",
            "follower_count",
            "following_count",
            "region",
            "organization",
            "is_key_monitored_account",
            "related_post_count",
            "view_or_play_count",
            "like_count",
            "comment_count",
            "repost_count",
            "favorite_count",
            "total_interaction_count",
            "collected_at",
        ])
        self.assertEqual(table5["follower_count"], 0)
        self.assertEqual(table5["view_or_play_count"], 0)
        self.assertIsNone(table5["organization"])

    def test_delivery_uses_dependency_order_and_retries_pending_event(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            formal = root / "formal"
            formal.mkdir()
            pending = root / "pending.jsonl"
            payload_root = root / "payloads"

            rows = {
                "table1": {"content_id": "p1", "platform": "微博"},
                "table2": {"content_id": "p1", "comment_id": "c1", "platform": "微博"},
                "table3": {"content_id": "p1", "platform": "微博"},
                "table4": {"content_id": "p1", "comment_id": "c1", "platform": "微博"},
                "table5": {"account_id": "u1", "platform": "微博"},
            }
            table_files = {}
            names = {
                "table1": "table1_content.jsonl",
                "table2": "table2_comments.jsonl",
                "table3": "table3_post_interactions.jsonl",
                "table4": "table4_comment_interactions.jsonl",
                "table5": "table5_accounts.jsonl",
            }
            for key, name in names.items():
                path = formal / name
                path.write_text(
                    json.dumps(rows[key], ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                table_files[key] = str(path)

            event = {
                "platform": "wb",
                "node_id": "wb01",
                "published_at": "2026-09-21T10:00:00+08:00",
                "published_groups": [TABLE12_GROUP, TABLE345_GROUP],
                "table_files": table_files,
            }

            calls = []
            failed_once = {"table2": False}

            def fake_post(base_url, api_key, table_key, payload, **kwargs):
                calls.append(table_key)
                if table_key == "table2" and not failed_once["table2"]:
                    failed_once["table2"] = True
                    return {
                        "ok": False,
                        "table": table_key,
                        "error": "simulated failure",
                    }
                return {
                    "ok": True,
                    "table": table_key,
                    "sent": len(payload),
                }

            with patch(
                "monitor.poms_batch_sender.post_batch",
                side_effect=fake_post,
            ):
                first = deliver_with_outbox(
                    event,
                    pending,
                    payload_root,
                    base_url="http://example.test",
                    api_key="secret",
                )
                second = deliver_with_outbox(
                    None,
                    pending,
                    payload_root,
                    base_url="http://example.test",
                    api_key="secret",
                )

            self.assertEqual(first["delivery_state"], "pending_retry")
            self.assertEqual(first["pending_events"], 1)
            self.assertEqual(second["delivery_state"], "delivered")
            self.assertEqual(second["pending_events"], 0)
            self.assertEqual(calls, [
                "table1",
                "table2",
                "table1",
                "table2",
                "table3",
                "table4",
                "table5",
            ])
            self.assertFalse(pending.exists())

    def test_missing_configuration_keeps_event_pending_without_network(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            formal = root / "formal"
            formal.mkdir()
            pending = root / "pending.jsonl"
            payload_root = root / "payloads"
            path = formal / "table1_content.jsonl"
            path.write_text("{}\n", encoding="utf-8")

            event = {
                "platform": "wb",
                "node_id": "wb01",
                "published_at": "2026-09-21T09:15:00+08:00",
                "published_groups": [TABLE12_GROUP],
                "table_files": {
                    "table1": str(path),
                    "table2": str(formal / "table2_comments.jsonl"),
                },
            }

            result = deliver_with_outbox(
                event,
                pending,
                payload_root,
                base_url="",
                api_key="",
            )
            self.assertEqual(
                result["delivery_state"],
                "pending_configuration",
            )
            self.assertTrue(pending.exists())
            self.assertIn("POMS_URL", result["missing"])
            self.assertIn("POMS_API_KEY", result["missing"])

    def test_expected_batch_endpoint_names(self):
        self.assertEqual(TABLE_ENDPOINTS, {
            "table1": "published_content_basic_information",
            "table2": "comment_basic_information",
            "table3": "published_content_interaction_data",
            "table4": "comment_content_interaction_data",
            "table5": "account_information",
        })


if __name__ == "__main__":
    unittest.main()
