from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import monitor.crawler_runner as crawler_runner
import run_single_platform


class _Proc:
    def __init__(self, returncode: int):
        self.returncode = returncode


class DouyinRealtimePolicyTests(unittest.TestCase):
    def setUp(self):
        self.original_detail = crawler_runner._run_detail_comment_recovery
        if hasattr(crawler_runner, "_promotion_week_dy_realtime_policy"):
            delattr(crawler_runner, "_promotion_week_dy_realtime_policy")

    def tearDown(self):
        crawler_runner._run_detail_comment_recovery = self.original_detail
        if hasattr(crawler_runner, "_promotion_week_dy_realtime_policy"):
            delattr(crawler_runner, "_promotion_week_dy_realtime_policy")

    def test_one_failed_candidate_does_not_abort_later_candidate(self):
        run_single_platform._install_douyin_realtime_policy()
        patched = crawler_runner._run_detail_comment_recovery

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out_dir = root / "out"
            out_dir.mkdir()
            stdout = root / "stdout.log"
            stderr = root / "stderr.log"
            cfg = {
                "realtime_mode": True,
                "douyin_realtime_detail_budget_seconds": 120,
                "douyin_realtime_max_comments_per_video": 100,
                "login_type": "qrcode",
                "max_concurrency_num": 1,
                "get_sub_comment": "yes",
                "save_data_option": "jsonl",
                "media_crawler_root": str(root),
            }

            with mock.patch("run_single_platform.subprocess.run", side_effect=[_Proc(1), _Proc(0)]) as run_mock:
                rc, attempts = patched(
                    cfg,
                    "dy",
                    ["https://www.douyin.com/video/1", "https://www.douyin.com/video/2"],
                    out_dir,
                    stdout,
                    stderr,
                    batch_size=1,
                )

            self.assertEqual(rc, 0)
            self.assertEqual(attempts, 2)
            self.assertEqual(run_mock.call_count, 2)
            text = stdout.read_text(encoding="utf-8")
            self.assertIn("DOUYIN_REALTIME_DETAIL_CANDIDATE_FAILED", text)
            self.assertIn("DOUYIN_REALTIME_DETAIL_CANDIDATE_SUCCESS", text)

    def test_douyin_policy_does_not_replace_other_platform_behavior(self):
        called = []

        def original(cfg, platform, candidates, output_dir, stdout_log, stderr_log, *, batch_size=None):
            called.append(platform)
            return 7, 3

        crawler_runner._run_detail_comment_recovery = original
        run_single_platform._install_douyin_realtime_policy()
        patched = crawler_runner._run_detail_comment_recovery

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stdout = root / "stdout.log"
            stderr = root / "stderr.log"
            result = patched(
                {"realtime_mode": True},
                "xhs",
                ["one"],
                root,
                stdout,
                stderr,
                batch_size=1,
            )

        self.assertEqual(result, (7, 3))
        self.assertEqual(called, ["xhs"])


if __name__ == "__main__":
    unittest.main()
