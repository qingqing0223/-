from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard_adapter.suqi_pusher import to_suqi_record
from monitor.ingest import ingest_and_classify
from monitor.kuaishou_key_accounts import load_kuaishou_key_accounts, match_kuaishou_key_account
from pipeline.io_utils import read_jsonl
from pipeline.normalizer import normalize_record
from run_single_platform import _apply_kuaishou_cadence


class KuaishouTimeScopeAndSnapshotTests(unittest.TestCase):
    def test_kuaishou_dedupe_merges_keywords_and_filters_generic_hits(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "search_contents.jsonl"
            raw.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in [
                {"photo_id": "same", "title": "2026年民族团结进步宣传周启动", "publish_time": "2026-09-16T01:00:00+08:00", "source_keyword": "关键词A"},
                {"photo_id": "same", "title": "2026年民族团结进步宣传周启动", "publish_time": "2026-09-16T01:00:00+08:00", "source_keyword": "关键词B"},
                {"photo_id": "generic", "title": "日常民族团结工作", "publish_time": "2026-09-16T01:00:00+08:00", "source_keyword": "民族团结"},
            ]), encoding="utf-8")
            result = ingest_and_classify(
                "ks", [raw], root / "state" / "seen.json",
                root / "classified" / "classified_results.jsonl",
                monitoring_start_time="2026-09-16T00:00:00+08:00",
                enable_classification=False,
            )
            rows = result["_classified_rows"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source_keywords"], ["关键词A", "关键词B"])
            self.assertEqual(result["filtered_topic_irrelevant"], 1)

    def test_cadence_override_is_kuaishou_only(self):
        shared = {"realtime_mode": True, "interval_seconds": 300}
        other = dict(shared)
        _apply_kuaishou_cadence(other, "dy")
        self.assertEqual(other["interval_seconds"], 300)

        kuaishou = dict(shared)
        _apply_kuaishou_cadence(kuaishou, "ks")
        self.assertEqual(kuaishou["interval_seconds"], 900)
        self.assertEqual(kuaishou["realtime_comment_refresh_seconds"], 900)

    def test_name_only_is_candidate_and_stable_id_is_verified(self):
        registry = {"accounts": [{
            "canonical_name": "人民日报", "aliases": [], "account_ids": ["verified-1"],
            "profile_urls": [], "category": "中央媒体", "institution": "人民日报社",
            "enabled": True,
        }]}
        candidate = match_kuaishou_key_account(
            {"author": "人民日报", "author_id": "impostor"}, registry
        )
        self.assertFalse(candidate["is_key_monitor_account"])
        self.assertEqual(candidate["key_account_match_status"], "name_candidate_unverified")
        verified = match_kuaishou_key_account(
            {"author": "任意显示名", "author_id": "verified-1"}, registry
        )
        self.assertTrue(verified["is_key_monitor_account"])
        self.assertEqual(verified["key_account_match_basis"], "stable_account_id")

    def test_tech_design_registry_contains_all_four_media_categories(self):
        registry = load_kuaishou_key_accounts(
            Path(__file__).resolve().parents[1] / "config" / "kuaishou_key_accounts.json"
        )
        categories = {row["category"] for row in registry["accounts"]}
        self.assertEqual(categories, {"中央媒体", "统战系统媒体", "卫视媒体", "地方媒体"})
        self.assertGreaterEqual(len(registry["accounts"]), 50)
        self.assertTrue(all(not row["account_ids"] for row in registry["accounts"]))

    def test_missing_public_metrics_remain_null_with_reason(self):
        row = normalize_record({
            "photo_id": "p1",
            "caption": "测试",
            "title": "测试内容",
            "publish_time": "2026-09-16T00:00:00+08:00",
        }, platform_hint="ks")
        self.assertIsNotNone(row)
        self.assertIsNone(row["likes"])
        self.assertIsNone(row["views"])
        self.assertEqual(row["metric_missing_reasons"]["likes"], "field_missing_or_unparseable")
        dashboard_row = to_suqi_record(row)
        self.assertIsNone(dashboard_row["likes"])
        self.assertIsNone(dashboard_row["comments"])

    def test_strict_beijing_scope_and_one_hour_append_only_snapshots(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "search_contents.jsonl"
            comments_raw = root / "search_comments.jsonl"
            state = root / "state" / "seen_ids.json"
            classified = root / "classified" / "classified_results.jsonl"
            registry_path = root / "kuaishou_key_accounts.json"
            registry_path.write_text(json.dumps({
                "platform": "ks", "key_content_ids": [],
                "accounts": [{
                    "canonical_name": "重点账号", "aliases": [],
                    "account_ids": ["account-1"], "profile_urls": [],
                    "category": "中央媒体", "institution": "测试机构", "enabled": True,
                }],
            }, ensure_ascii=False), encoding="utf-8")
            rows = [
                {"photo_id": "valid", "title": "2026年民族团结进步宣传周 有效", "publish_time": "2026-09-16 00:00:00", "view_count": 10, "author_id": "account-1", "nickname": "重点账号", "fans_count": 100, "following_count": 5},
                {"photo_id": "ordinary", "title": "2026年民族团结进步宣传周 普通账号内容", "publish_time": "2026-09-16 01:00:00", "view_count": 20, "author_id": "account-2", "nickname": "普通账号"},
                {"photo_id": "old", "title": "2026年民族团结进步宣传周 过早", "publish_time": "2026-09-15T23:59:59+08:00"},
                {"photo_id": "late", "title": "2026年民族团结进步宣传周 过晚", "publish_time": "2026-09-17T00:00:00+08:00"},
                {"photo_id": "missing", "title": "2026年民族团结进步宣传周 缺时间"},
                {"photo_id": "bad", "title": "2026年民族团结进步宣传周 坏时间", "publish_time": "昨天"},
            ]
            raw.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
            comments_raw.write_text(json.dumps({
                "comment_id": "comment-1",
                "photo_id": "valid",
                "content": "评论",
                "create_time": "2026-09-16T00:30:00+08:00",
                "like_count": 3,
                "reply_count": 2,
            }, ensure_ascii=False) + "\n", encoding="utf-8")

            with patch("monitor.ingest.classify_records", side_effect=lambda records, concurrency=4: records):
                first = ingest_and_classify(
                    "ks", [raw, comments_raw], state, classified,
                    monitoring_start_time="2026-09-16T00:00:00+08:00",
                    monitoring_end_time="2026-09-17T00:00:00+08:00",
                    observed_at="2026-09-16T01:00:00+08:00",
                    key_accounts_config_path=str(registry_path),
                    enable_classification=False,
                )
                second = ingest_and_classify(
                    "ks", [raw, comments_raw], state, classified,
                    monitoring_start_time="2026-09-16T00:00:00+08:00",
                    monitoring_end_time="2026-09-17T00:00:00+08:00",
                    observed_at="2026-09-16T01:30:00+08:00",
                    key_accounts_config_path=str(registry_path),
                    enable_classification=False,
                )
                third = ingest_and_classify(
                    "ks", [raw, comments_raw], state, classified,
                    monitoring_start_time="2026-09-16T00:00:00+08:00",
                    monitoring_end_time="2026-09-17T00:00:00+08:00",
                    observed_at="2026-09-16T02:00:00+08:00",
                    key_accounts_config_path=str(registry_path),
                    enable_classification=False,
                )

            self.assertEqual(first["classified_records"], 3)
            self.assertFalse(first["classification_enabled"])
            self.assertEqual(first["filtered_before_start"], 1)
            self.assertEqual(first["filtered_at_or_after_end"], 1)
            self.assertEqual(first["filtered_missing_publish_time"], 1)
            self.assertEqual(first["filtered_unparseable_publish_time"], 1)
            self.assertEqual(first["engagement_snapshots"]["snapshot_records"], 2)
            self.assertEqual(second["engagement_snapshots"]["snapshot_records"], 0)
            self.assertEqual(third["engagement_snapshots"]["snapshot_records"], 2)

            snapshots = list(read_jsonl(classified.parent / "kuaishou_engagement_snapshots.jsonl"))
            self.assertEqual(len(snapshots), 4)
            self.assertTrue(all(row["is_key_monitor_content"] for row in snapshots))
            self.assertEqual(snapshots[0]["statistics_time"], "2026-09-16T01:00:00+08:00")
            self.assertEqual(snapshots[2]["statistics_time"], "2026-09-16T02:00:00+08:00")
            self.assertEqual(snapshots[0]["metrics"]["view_or_play_count"], 10)
            self.assertIsNone(snapshots[0]["metrics"]["like_count"])
            self.assertIn("like_count", snapshots[0]["missing_reasons"])
            comment_snapshot = next(row for row in snapshots if row["entity_type"] == "comment")
            self.assertEqual(comment_snapshot["metrics"]["like_count"], 3)
            self.assertEqual(comment_snapshot["metrics"]["reply_count"], 2)
            accounts = list(read_jsonl(classified.parent / "kuaishou_account_snapshots.jsonl"))
            self.assertEqual(len(accounts), 4)
            key_account = next(
                row for row in accounts
                if row["account_attributes"]["account_id"] == "account-1"
            )
            self.assertTrue(key_account["account_attributes"]["is_key_monitor_account"])
            self.assertEqual(key_account["account_attributes"]["follower_count"], 100)
            self.assertEqual(key_account["account_attributes"]["following_count"], 5)
            self.assertEqual(key_account["monitoring_period_aggregates"]["related_post_count"], 1)


if __name__ == "__main__":
    unittest.main()
