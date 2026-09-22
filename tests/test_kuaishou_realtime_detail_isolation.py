from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import monitor.crawler_runner as crawler_runner
import run_single_platform


class _Proc:
    def __init__(self, returncode: int):
        self.returncode = returncode

    def wait(self, timeout=None):
        return self.returncode


class KuaishouRealtimeDetailIsolationTests(unittest.TestCase):
    def setUp(self):
        self.original_update = crawler_runner._update_queue_from_content
        self.original_detail = crawler_runner._run_detail_comment_recovery
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
        crawler_runner._classify_state = self.original_classify
        if self.original_fallback_flag is None:
            if hasattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback"):
                delattr(crawler_runner, "_promotion_week_ks_unknown_count_fallback")
        else:
            crawler_runner._promotion_week_ks_unknown_count_fallback = self.original_fallback_flag
        if self.original_classifier_flag is None:
            if hasattr(crawler_runner, "_promotion_week_ks_precise_failure_classifier"):
                delattr(crawler_runner, "_promotion_week_ks_precise_failure_classifier")
        else:
            crawler_runner._promotion_week_ks_precise_failure_classifier = self.original_classifier_flag

    def test_first_candidate_failure_does_not_abort_second_candidate(self):
        run_single_platform._install_kuaishou_unknown_comment_queue_fallback()
        patched = crawler_runner._run_detail_comment_recovery
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stdout = root / "stdout.log"
            stderr = root / "stderr.log"
            stdout.write_text("", encoding="utf-8")
            stderr.write_text("", encoding="utf-8")
            cfg = {
                "realtime_mode": True,
                "media_crawler_root": td,
                "login_type": "qrcode",
                "max_concurrency_num": 1,
                "get_sub_comment": "yes",
                "save_data_option": "jsonl",
                "kuaishou_realtime_detail_budget_seconds": 120,
                "kuaishou_realtime_max_comments_per_video": 100,
            }
            with (
                patch.object(run_single_platform, "_kuaishou_cdp_preflight", return_value=(True, "ok")),
                patch.object(run_single_platform.subprocess, "Popen", side_effect=[_Proc(1), _Proc(0)]) as mocked,
            ):
                rc, attempts = patched(
                    cfg,
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
            self.assertIn("KUAISHOU_REALTIME_DETAIL_CANDIDATE_FAILED", text)
            self.assertIn("continuing_with_next_candidate=yes", text)
            self.assertIn("KUAISHOU_REALTIME_DETAIL_CANDIDATE_SUCCESS", text)

    def test_persisted_content_and_comments_make_failed_tail_partial_success(self):
        run_single_platform._install_kuaishou_precise_failure_classifier()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stdout = root / "stdout.log"
            stderr = root / "stderr.log"
            stdout.write_text("earlier HTTP 502 warning", encoding="utf-8")
            stderr.write_text("later detail candidate failed", encoding="utf-8")
            state = crawler_runner._classify_state(
                1,
                stdout,
                stderr,
                content_row_count=120,
                comment_row_count=12,
                comments_enabled=True,
            )
            self.assertEqual(state, "PARTIAL_SUCCESS")


if __name__ == "__main__":
    unittest.main()
