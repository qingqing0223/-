from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from monitor.crawler_runner import _classify_state
from monitor.ingest import _prepare_region_aliases
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
            "status": "neutral",
            "type": None,
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
