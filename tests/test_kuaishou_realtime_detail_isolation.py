from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import monitor.crawler_runner as crawler_runner
import run_single_platform


class _Proc:
    def __init__(self, returncode: int, on_wait=None):
        self.returncode = returncode
        self._on_wait = on_wait

    def wait(self, timeout=None):
        if self._on_wait:
            self._on_wait()
        return self.returncode

    def poll(self):
        return self.returncode


class KuaishouRealtimeDetailIsolationTests(unittest.TestCase):
    def setUp(self):
        self.original_update = crawler_runner._update_queue_from_content
        self.original_detail = crawler_runner._run_detail_comment_recovery
        self.original_mark = crawler_runner._mark_queue_batch
        self.original_classify = crawler_runner._classify_state
        self.original_fallback_flag = getattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback", None)
        self.original_classifier_flag = getattr(crawler_runner, "_promotion_week_ks_precise_failure_classifier", None)
        if hasattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback"):
            delattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback")
        if hasattr(crawler_runner, "_promotion_week_ks_precise_failure_classifier"):
            delattr(crawler_runner, "_promotion_week_ks_precise_failure_classifier")

    def tearDown(self):
        crawler_runner._update_queue_from_content = self.original_update
        crawler_runner._run_detail_comment_recovery = self.original_detail
        crawler_runner._mark_queue_batch = self.original_mark
        crawler_runner._classify_state = self.original_classify
        for name, value in (
            ("_promotion_week_ks_unknown_count_fallback", self.original_fallback_flag),
            ("_promotion_week_ks_precise_failure_classifier", self.original_classifier_flag),
        ):
            if value is None:
                if hasattr(crawler_runner, name):
                    delattr(crawler_runner, name)
            else:
                setattr(crawler_runner, name, value)

    def _cfg(self, td):
        return {
            "realtime_mode": True,
            "media_crawler_root": td,
            "login_type": "qrcode",
            "max_concurrency_num": 1,
            "get_sub_comment": "yes",
            "save_data_option": "jsonl",
            "kuaishou_realtime_detail_budget_seconds": 120,
            "kuaishou_realtime_candidate_timeout_seconds": 60,
            "kuaishou_realtime_max_comments_per_video": 100,
        }

    def test_no_external_cdp_port_is_required_and_second_candidate_can_succeed(self):
        run_single_platform._install_kuaishou_unknown_comment_queue_fallback()
        patched = crawler_runner._run_detail_comment_recovery
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stdout = root / "stdout.log"
            stderr = root / "stderr.log"
            stdout.write_text("", encoding="utf-8")
            stderr.write_text("", encoding="utf-8")

            def persist_comment():
                p = root / "ks_comments.jsonl"
                p.write_text('{"comment_id":"c1","content":"ok"}\n', encoding="utf-8")

            with patch.object(
                run_single_platform.subprocess,
                "Popen",
                side_effect=[_Proc(1), _Proc(0, persist_comment)],
            ) as mocked:
                rc, attempts = patched(
                    self._cfg(td),
                    "ks",
                    ["https://www.kuaishou.com/short-video/a", "https://www.kuaishou.com/short-video/b"],
                    root,
                    stdout,
                    stderr,
                    batch_size=2,
                )

            self.assertEqual(rc, 0)
            self.assertEqual(attempts, 2)
            self.assertEqual(mocked.call_count, 2)
            text = stdout.read_text(encoding="utf-8")
            self.assertIn("external_cdp_preflight=no", text)
            self.assertNotIn("KUAISHOU_REALTIME_DETAIL_CDP_UNAVAILABLE", text)
            self.assertIn("KUAISHOU_REALTIME_DETAIL_CANDIDATE_FAILED", text)
            self.assertIn("KUAISHOU_REALTIME_DETAIL_CANDIDATE_SUCCESS", text)

    def test_rc_zero_without_comment_jsonl_is_not_marked_success(self):
        run_single_platform._install_kuaishou_unknown_comment_queue_fallback()
        patched = crawler_runner._run_detail_comment_recovery
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stdout = root / "stdout.log"
            stderr = root / "stderr.log"
            stdout.write_text("", encoding="utf-8")
            stderr.write_text("", encoding="utf-8")
            with patch.object(run_single_platform.subprocess, "Popen", return_value=_Proc(0)):
                rc, attempts = patched(
                    self._cfg(td), "ks", ["v1"], root, stdout, stderr, batch_size=1
                )
            self.assertEqual(rc, 0)
            self.assertEqual(attempts, 1)
            self.assertIn(
                "KUAISHOU_REALTIME_DETAIL_CANDIDATE_EMPTY",
                stdout.read_text(encoding="utf-8"),
            )

    def test_empty_candidate_is_deferred_after_clean_zero_comment_result(self):
        run_single_platform._install_kuaishou_unknown_comment_queue_fallback()
        patched = crawler_runner._run_detail_comment_recovery
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stdout = root / "stdout.log"
            stderr = root / "stderr.log"
            stdout.write_text("", encoding="utf-8")
            stderr.write_text("", encoding="utf-8")
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
                    },
                    "v2": {
                        "visible_comment_count": 1,
                        "retry_count": 0,
                        "last_deep_crawled_at": "",
                        "last_deep_attempt_at": "",
                        "last_deep_outcome": "",
                        "next_retry_at": "",
                    },
                },
            }
            cfg = self._cfg(td)
            cfg["ks_realtime_empty_retry_seconds"] = 1800

            with patch.object(run_single_platform.subprocess, "Popen", return_value=_Proc(0)):
                rc, attempts = patched(
                    cfg, "ks", ["v1"], root, stdout, stderr, batch_size=1
                )

            self.assertEqual(rc, 0)
            self.assertEqual(attempts, 1)
            crawler_runner._mark_queue_batch(queue, ["v1"], True)

            self.assertEqual(queue["items"]["v1"]["last_deep_outcome"], "empty")
            self.assertTrue(queue["items"]["v1"]["next_retry_at"])
            self.assertEqual(
                crawler_runner._select_queue_candidates(
                    queue, max_items=2, refresh_seconds=900
                ),
                ["v2"],
            )

    def test_persisted_content_and_comments_make_failed_tail_partial_success(self):
        run_single_platform._install_kuaishou_precise_failure_classifier()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stdout = root / "stdout.log"
            stderr = root / "stderr.log"
            stdout.write_text("earlier HTTP 502 warning", encoding="utf-8")
            stderr.write_text("later detail candidate failed", encoding="utf-8")
            state = crawler_runner._classify_state(
                1, stdout, stderr,
                content_row_count=120,
                comment_row_count=12,
                comments_enabled=True,
            )
            self.assertEqual(state, "PARTIAL_SUCCESS")


if __name__ == "__main__":
    unittest.main()
