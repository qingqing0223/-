from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from monitor.crawler_runner import (
    _classify_state,
    _detail_recovery_candidates,
    _mark_queue_outcome,
    _select_queue_candidates,
)
from monitor.ingest import _prepare_region_aliases
from pipeline.classifier import classify_records
from pipeline.normalizer import normalize_record
from dashboard_adapter.suqi_pusher import to_suqi_record


class MonitoringRegressionTests(unittest.TestCase):
    def _logs(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        out = root / "stdout.log"
        err = root / "stderr.log"
        out.write_text("", encoding="utf-8")
        err.write_text("", encoding="utf-8")
        return tmp, out, err

    def test_soft_empty_state_is_healthy_status_contract(self):
        text = (Path(__file__).resolve().parents[1] / "monitor" / "crawler_runner.py").read_text(encoding="utf-8")
        self.assertIn('if state in {"NATURAL_END", "SOFT_EMPTY"}:', text)
        orchestrator = (Path(__file__).resolve().parents[1] / "monitor" / "orchestrator.py").read_text(encoding="utf-8")
        self.assertIn('"soft_empty_no_jsonl" if run.state == "SOFT_EMPTY"', orchestrator)

    def test_zero_exit_without_jsonl_is_soft_empty(self):
        tmp, out, err = self._logs()
        try:
            state = _classify_state(
                0, out, err,
                content_row_count=0,
                comment_row_count=0,
                comments_enabled=True,
            )
            self.assertEqual(state, "SOFT_EMPTY")
        finally:
            tmp.cleanup()

    def test_content_without_comment_rows_is_visible_state(self):
        tmp, out, err = self._logs()
        try:
            state = _classify_state(
                0, out, err,
                content_row_count=10,
                comment_row_count=0,
                comments_enabled=True,
            )
            self.assertEqual(state, "SUCCESS_NO_COMMENTS")
        finally:
            tmp.cleanup()

    def test_successful_rows_beat_recovered_transport_warning(self):
        tmp, out, err = self._logs()
        try:
            out.write_text(
                "CDP browser launch failed: HTTP 502; fallback to standard mode; later collection completed",
                encoding="utf-8",
            )
            state = _classify_state(
                0, out, err,
                content_row_count=124,
                comment_row_count=12,
                comments_enabled=True,
            )
            self.assertEqual(state, "SUCCESS")
        finally:
            tmp.cleanup()

    def test_recovered_douyin_cdp_502_with_clean_empty_search_is_soft_empty(self):
        tmp, out, err = self._logs()
        try:
            err.write_text(
                "[CDPBrowserManager] CDP connection failed: HTTP 502\n"
                "[DouYinCrawler] CDP模式启动失败，回退到标准模式: HTTP 502\n"
                "[DouYinCrawler.search] search douyin keyword: test, page: 1 is empty,[]\n"
                "[DouYinCrawler.start] Douyin Crawler finished ...\n",
                encoding="utf-8",
            )
            state = _classify_state(
                0, out, err,
                content_row_count=0,
                comment_row_count=0,
                comments_enabled=True,
            )
            self.assertEqual(state, "SOFT_EMPTY")
        finally:
            tmp.cleanup()

    def test_transport_error_still_detected_when_run_failed(self):
        tmp, out, err = self._logs()
        try:
            err.write_text("Page.goto timed out after HTTP 502", encoding="utf-8")
            state = _classify_state(
                1, out, err,
                content_row_count=0,
                comment_row_count=0,
                comments_enabled=True,
            )
            self.assertEqual(state, "NETWORK_ERROR")
        finally:
            tmp.cleanup()

    def test_verification_marker_beats_zero_exit(self):
        tmp, out, err = self._logs()
        try:
            out.write_text("SEARCH_MANUAL_VERIFY_REQUIRED 验证码", encoding="utf-8")
            state = _classify_state(
                0, out, err,
                content_row_count=0,
                comment_row_count=0,
                comments_enabled=True,
            )
            self.assertEqual(state, "VERIFY_REQUIRED")
        finally:
            tmp.cleanup()

    def test_detail_recovery_selects_only_items_with_visible_comments(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "search_contents_2026-09-17.jsonl"
            rows = [
                {"aweme_id": "a1", "aweme_url": "https://www.douyin.com/video/a1", "comment_count": 3},
                {"aweme_id": "a2", "aweme_url": "https://www.douyin.com/video/a2", "comment_count": 0},
                {"aweme_id": "a1", "aweme_url": "https://www.douyin.com/video/a1", "comment_count": 3},
                {"aweme_id": "a3", "aweme_url": "https://www.douyin.com/video/a3", "comment_count": "1万"},
            ]
            path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
            got = _detail_recovery_candidates("dy", [path], 10)
            self.assertEqual(got, ["https://www.douyin.com/video/a1", "https://www.douyin.com/video/a3"])

    def test_kuaishou_unknown_comment_count_enters_bounded_realtime_queue(self):
        import monitor.crawler_runner as crawler_runner
        from run_single_platform import _install_kuaishou_unknown_comment_queue_fallback

        original_update = crawler_runner._update_queue_from_content
        original_detail = crawler_runner._run_detail_comment_recovery
        original_flag = getattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback", None)
        try:
            if hasattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback"):
                delattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback")
            crawler_runner._update_queue_from_content = original_update
            crawler_runner._run_detail_comment_recovery = original_detail
            _install_kuaishou_unknown_comment_queue_fallback()

            self.assertIsNot(crawler_runner._run_detail_comment_recovery, original_detail)
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "search_contents_2026-09-17.jsonl"
                path.write_text(
                    json.dumps({
                        "video_id": "ks-video-1",
                        "video_url": "https://www.kuaishou.com/short-video/ks-video-1",
                        "comment_count": 0,
                    }, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                queue = {"version": 1, "items": {}}
                crawler_runner._update_queue_from_content("ks", [path], queue)
                item = queue["items"]["https://www.kuaishou.com/short-video/ks-video-1"]
                self.assertTrue(item["comment_count_unknown"])
                self.assertEqual(item["queue_signal"], "kuaishou_unknown_comment_count")
                self.assertEqual(item["visible_comment_count"], 1)
                got = crawler_runner._select_queue_candidates(queue, max_items=12, refresh_seconds=300)
                self.assertEqual(got, ["https://www.kuaishou.com/short-video/ks-video-1"])
        finally:
            crawler_runner._update_queue_from_content = original_update
            crawler_runner._run_detail_comment_recovery = original_detail
            if original_flag is None:
                if hasattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback"):
                    delattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback")
            else:
                crawler_runner._promotion_week_ks_unknown_count_fallback = original_flag

    def test_deep_queue_empty_candidate_cools_down_and_does_not_starve_fresh_video(self):
        queue = {
            "version": 1,
            "items": {
                "old-empty": {
                    "visible_comment_count": 1,
                    "retry_count": 0,
                    "last_deep_crawled_at": "",
                    "last_deep_attempt_at": "",
                    "last_deep_outcome": "",
                    "next_retry_at": "",
                },
                "fresh-video": {
                    "visible_comment_count": 1,
                    "retry_count": 0,
                    "last_deep_crawled_at": "",
                    "last_deep_attempt_at": "",
                    "last_deep_outcome": "",
                    "next_retry_at": "",
                },
            },
        }

        _mark_queue_outcome(
            queue,
            ["old-empty"],
            "empty",
            empty_retry_seconds=1800,
        )

        got = _select_queue_candidates(queue, max_items=4, refresh_seconds=900)
        self.assertEqual(got, ["fresh-video"])
        self.assertEqual(queue["items"]["old-empty"]["last_deep_outcome"], "empty")
        self.assertTrue(queue["items"]["old-empty"]["next_retry_at"])

    def test_deep_queue_failed_candidate_uses_exponential_backoff(self):
        queue = {
            "version": 1,
            "items": {
                "v1": {
                    "visible_comment_count": 1,
                    "retry_count": 0,
                    "last_deep_crawled_at": "",
                    "last_deep_attempt_at": "",
                    "last_deep_outcome": "",
                    "next_retry_at": "",
                }
            },
        }

        _mark_queue_outcome(
            queue,
            ["v1"],
            "timeout",
            failed_retry_base_seconds=600,
            failed_retry_cap_seconds=3600,
        )
        first_next = queue["items"]["v1"]["next_retry_at"]
        self.assertEqual(queue["items"]["v1"]["retry_count"], 1)
        self.assertEqual(
            _select_queue_candidates(queue, max_items=4, refresh_seconds=900),
            [],
        )

        queue["items"]["v1"]["next_retry_at"] = ""
        _mark_queue_outcome(
            queue,
            ["v1"],
            "timeout",
            failed_retry_base_seconds=600,
            failed_retry_cap_seconds=3600,
        )
        self.assertEqual(queue["items"]["v1"]["retry_count"], 2)
        self.assertNotEqual(queue["items"]["v1"]["next_retry_at"], first_next)

    def test_legacy_retry_count_is_ranked_after_never_attempted_candidate(self):
        queue = {
            "version": 1,
            "items": {
                "legacy-failed": {
                    "visible_comment_count": 10,
                    "retry_count": 3,
                    "last_deep_crawled_at": "",
                },
                "fresh-video": {
                    "visible_comment_count": 1,
                    "retry_count": 0,
                    "last_deep_crawled_at": "",
                },
            },
        }

        got = _select_queue_candidates(queue, max_items=2, refresh_seconds=900)
        self.assertEqual(got[0], "fresh-video")
        self.assertEqual(got[1], "legacy-failed")

    def test_region_aliases_cover_realistic_nested_platform_shapes(self):
        cases = [
            ({"ip_label": "IP属地：山东"}, "山东"),
            ({"user": {"ip_region": "北京"}}, "北京"),
            ({"user_info": {"ip_location": "来自：广东"}}, "广东"),
            ({"author": {"province": "四川省"}}, "四川"),
            ({"member": {"ip_region": "浙江"}}, "浙江"),
            ({"reply_control": {"location": "IP属地：上海"}}, "上海"),
            ({"region_name": "内蒙古自治区"}, "内蒙古"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                got = _prepare_region_aliases(raw)
                self.assertEqual(got.get("ip_location"), expected)

    def test_comment_hierarchy_keeps_content_parent_and_root_ids(self):
        raw = {
            "comment_id": "reply-2",
            "parent_comment_id": "root-1",
            "root_comment_id": "root-1",
            "aweme_id": "video-9",
            "content": "楼中楼回复",
            "ip_region": "北京",
        }
        raw = _prepare_region_aliases(raw)
        row = normalize_record(raw, source_file="search_comments.jsonl", platform_hint="dy")
        self.assertIsNotNone(row)
        self.assertEqual(row["record_type"], "comment")
        self.assertEqual(row["content_id"], "video-9")
        self.assertEqual(row["comment_id"], "reply-2")
        self.assertEqual(row["parent_comment_id"], "root-1")
        self.assertEqual(row["root_comment_id"], "root-1")
        self.assertEqual(row["comment_level"], 2)
        self.assertEqual(row["ip_location"], "北京")

    def test_classifier_outage_preserves_comment_and_hierarchy(self):
        record = {
            "sample_id": "reply-2",
            "dedupe_key": "ks:reply-2",
            "platform": "ks",
            "record_type": "comment",
            "content_id": "video-9",
            "comment_id": "reply-2",
            "parent_comment_id": "root-1",
            "root_comment_id": "root-1",
            "comment_level": 2,
            "content": "楼中楼回复",
            "analysis_text": "楼中楼回复",
            "context": "",
            "ip_location": "山东",
        }
        with patch("pipeline.classifier.OpinionMonitorV2") as mocked:
            mocked.return_value.classify_many.side_effect = RuntimeError("Arrearage")
            rows = classify_records([record], concurrency=1)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["record_type"], "comment")
        self.assertEqual(row["parent_comment_id"], "root-1")
        self.assertEqual(row["root_comment_id"], "root-1")
        self.assertEqual(row["ip_location"], "山东")
        self.assertFalse(row["classification_ok"])
        self.assertEqual(row["classification_state"], "degraded")
        self.assertEqual(row["status"], "unclassified")

    def test_dashboard_record_exposes_hierarchy_as_structured_fields(self):
        row = {
            "platform": "dy",
            "sample_id": "reply-2",
            "record_type": "comment",
            "content_id": "video-9",
            "comment_id": "reply-2",
            "parent_comment_id": "root-1",
            "root_comment_id": "root-1",
            "comment_level": 2,
            "sub_comment_count": 0,
            "content": "楼中楼回复",
            "status": "attention",
            "type": "neutral",
        }
        record = to_suqi_record(row)
        self.assertEqual(record["record_type"], "comment")
        self.assertEqual(record["content_id"], "video-9")
        self.assertEqual(record["comment_id"], "reply-2")
        self.assertEqual(record["parent_comment_id"], "root-1")
        self.assertEqual(record["root_comment_id"], "root-1")
        self.assertEqual(record["comment_level"], 2)


if __name__ == "__main__":
    unittest.main()
