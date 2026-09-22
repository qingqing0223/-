from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from monitor.crawler_runner import _classify_state, _detail_recovery_candidates
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
        original_mark = crawler_runner._mark_queue_batch
        original_flag = getattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback", None)
        try:
            if hasattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback"):
                delattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback")
            crawler_runner._update_queue_from_content = original_update
            crawler_runner._run_detail_comment_recovery = original_detail
            crawler_runner._mark_queue_batch = original_mark
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

    def test_kuaishou_realtime_timeout_is_per_candidate_and_queue_marking_is_precise(self):
        import monitor.crawler_runner as crawler_runner
        from run_single_platform import _install_kuaishou_unknown_comment_queue_fallback

        original_update = crawler_runner._update_queue_from_content
        original_detail = crawler_runner._run_detail_comment_recovery
        original_mark = crawler_runner._mark_queue_batch
        original_flag = getattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback", None)

        class FakeProc:
            calls = 0

            def __init__(self, *args, **kwargs):
                self.pid = 9000 + FakeProc.calls
                self.returncode = None
                self.index = FakeProc.calls
                FakeProc.calls += 1

            def wait(self, timeout=None):
                self.timeout = timeout
                if self.index == 0 and self.returncode is None:
                    raise subprocess.TimeoutExpired("uv", timeout)
                self.returncode = 0
                return 0

            def poll(self):
                return self.returncode

        try:
            if hasattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback"):
                delattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback")
            crawler_runner._update_queue_from_content = original_update
            crawler_runner._run_detail_comment_recovery = original_detail
            crawler_runner._mark_queue_batch = original_mark
            _install_kuaishou_unknown_comment_queue_fallback()

            queue = {
                "items": {
                    "a": {"last_deep_crawled_at": "", "retry_count": 0},
                    "b": {"last_deep_crawled_at": "", "retry_count": 0},
                    "c": {"last_deep_crawled_at": "", "retry_count": 0},
                }
            }
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                out = root / "stdout.log"
                err = root / "stderr.log"
                out.write_text("", encoding="utf-8")
                err.write_text("", encoding="utf-8")
                cfg = {
                    "realtime_mode": True,
                    "media_crawler_root": td,
                    "kuaishou_realtime_detail_budget_seconds": 180,
                    "kuaishou_realtime_candidate_timeout_seconds": 40,
                    "get_sub_comment": "yes",
                }
                with patch("run_single_platform._kuaishou_cdp_preflight", return_value=(True, "ok")), \
                     patch("subprocess.Popen", side_effect=FakeProc) as popen, \
                     patch("monitor.final_realtime_policy._terminate_process_tree") as terminate:
                    rc, attempts = crawler_runner._run_detail_comment_recovery(
                        cfg, "ks", ["a", "b"], root, out, err
                    )
                    crawler_runner._mark_queue_batch(queue, ["a", "b"], rc == 0)

                self.assertEqual(attempts, 2)
                self.assertEqual(popen.call_count, 2)
                self.assertEqual(terminate.call_count, 1)
                self.assertEqual(queue["items"]["a"]["last_deep_crawled_at"], "")
                self.assertEqual(queue["items"]["a"]["retry_count"], 1)
                self.assertTrue(queue["items"]["b"]["last_deep_crawled_at"])
                self.assertEqual(queue["items"]["b"]["retry_count"], 0)
                self.assertEqual(queue["items"]["c"]["last_deep_crawled_at"], "")
                self.assertIn("candidate_timeout=40s", out.read_text(encoding="utf-8"))
                first_cmd = popen.call_args_list[0].args[0]
                self.assertEqual(first_cmd[first_cmd.index("--get_comment") + 1], "yes")
                self.assertEqual(first_cmd[first_cmd.index("--get_sub_comment") + 1], "yes")
        finally:
            crawler_runner._update_queue_from_content = original_update
            crawler_runner._run_detail_comment_recovery = original_detail
            crawler_runner._mark_queue_batch = original_mark
            if original_flag is None:
                if hasattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback"):
                    delattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback")
            else:
                crawler_runner._promotion_week_ks_unknown_count_fallback = original_flag

    def test_kuaishou_realtime_cdp_unavailable_keeps_every_candidate_unattempted(self):
        import monitor.crawler_runner as crawler_runner
        from run_single_platform import _install_kuaishou_unknown_comment_queue_fallback

        original_update = crawler_runner._update_queue_from_content
        original_detail = crawler_runner._run_detail_comment_recovery
        original_mark = crawler_runner._mark_queue_batch
        original_flag = getattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback", None)
        try:
            if hasattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback"):
                delattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback")
            crawler_runner._update_queue_from_content = original_update
            crawler_runner._run_detail_comment_recovery = original_detail
            crawler_runner._mark_queue_batch = original_mark
            _install_kuaishou_unknown_comment_queue_fallback()
            queue = {"items": {key: {"last_deep_crawled_at": "", "retry_count": 0} for key in ["a", "b"]}}
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                out = root / "stdout.log"
                err = root / "stderr.log"
                out.write_text("", encoding="utf-8")
                err.write_text("", encoding="utf-8")
                with patch("run_single_platform._kuaishou_cdp_preflight", return_value=(False, "test_unavailable")), \
                     patch("subprocess.Popen") as popen:
                    rc, attempts = crawler_runner._run_detail_comment_recovery(
                        {"realtime_mode": True, "media_crawler_root": td},
                        "ks", ["a", "b"], root, out, err,
                    )
                    crawler_runner._mark_queue_batch(queue, ["a", "b"], rc == 0)
                self.assertEqual(rc, 125)
                self.assertEqual(attempts, 0)
                popen.assert_not_called()
                self.assertEqual(queue["items"]["a"], {"last_deep_crawled_at": "", "retry_count": 0})
                self.assertEqual(queue["items"]["b"], {"last_deep_crawled_at": "", "retry_count": 0})
                self.assertIn("CDP_UNAVAILABLE", out.read_text(encoding="utf-8"))
        finally:
            crawler_runner._update_queue_from_content = original_update
            crawler_runner._run_detail_comment_recovery = original_detail
            crawler_runner._mark_queue_batch = original_mark
            if original_flag is None:
                if hasattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback"):
                    delattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback")
            else:
                crawler_runner._promotion_week_ks_unknown_count_fallback = original_flag

    def test_kuaishou_cdp_preflight_uses_json_version_and_playwright_handshake(self):
        from run_single_platform import _kuaishou_cdp_preflight

        response = MagicMock()
        response.read.return_value = json.dumps({
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/test"
        }).encode("utf-8")
        response.__enter__.return_value = response
        playwright = MagicMock()
        playwright.chromium.connect_over_cdp = AsyncMock(return_value=object())
        playwright.stop = AsyncMock()
        manager = MagicMock()
        manager.start = AsyncMock(return_value=playwright)
        with patch("urllib.request.urlopen", return_value=response) as urlopen, \
             patch("playwright.async_api.async_playwright", return_value=manager):
            ok, reason = _kuaishou_cdp_preflight(9222, timeout_seconds=0.5)
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")
        self.assertIn("/json/version", urlopen.call_args.args[0])
        playwright.chromium.connect_over_cdp.assert_awaited_once()
        playwright.stop.assert_awaited_once()

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
        with patch("pipeline.classifier._load_opinion_monitor_v2") as loader:
            mocked = loader.return_value
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
