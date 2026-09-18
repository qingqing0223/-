from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import monitor.crawler_runner as crawler_runner
import monitor.final_realtime_policy as policy


class _FakePopen:
    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.returncode = 0
        self.pid = 12345

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return self.returncode


class _TimeoutPopen(_FakePopen):
    def __init__(self, cmd, **kwargs):
        super().__init__(cmd, **kwargs)
        self.returncode = None

    def wait(self, timeout=None):
        raise policy.subprocess.TimeoutExpired(self.cmd, timeout)

    def poll(self):
        return None


class BilibiliFinalRealtimePolicyTests(unittest.TestCase):
    def setUp(self):
        self.original_detail = crawler_runner._run_detail_comment_recovery
        self.original_mark = crawler_runner._mark_queue_batch
        marker = "_promotion_week_final_realtime_policy_bili"
        if hasattr(crawler_runner, marker):
            delattr(crawler_runner, marker)

    def tearDown(self):
        crawler_runner._run_detail_comment_recovery = self.original_detail
        crawler_runner._mark_queue_batch = self.original_mark
        marker = "_promotion_week_final_realtime_policy_bili"
        if hasattr(crawler_runner, marker):
            delattr(crawler_runner, marker)

    def _cfg(self, root: Path):
        return {
            "realtime_mode": True,
            "login_type": "qrcode",
            "max_concurrency_num": 1,
            "get_sub_comment": "yes",
            "save_data_option": "jsonl",
            "media_crawler_root": str(root),
        }

    def test_bilibili_realtime_uses_small_comment_cap_and_nested_bounds(self):
        policy.install_final_realtime_policy("bili")
        patched = crawler_runner._run_detail_comment_recovery

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out_dir = root / "out"
            out_dir.mkdir()
            stdout = root / "stdout.log"
            stderr = root / "stderr.log"

            created = []

            def make_popen(cmd, **kwargs):
                p = _FakePopen(cmd, **kwargs)
                created.append(p)
                return p

            with mock.patch("monitor.final_realtime_policy.subprocess.Popen", side_effect=make_popen):
                rc, attempts = patched(
                    self._cfg(root),
                    "bili",
                    ["https://www.bilibili.com/video/av1"],
                    out_dir,
                    stdout,
                    stderr,
                    batch_size=1,
                )

            self.assertEqual(rc, 0)
            self.assertEqual(attempts, 1)
            self.assertEqual(len(created), 1)
            proc = created[0]
            cmd = proc.cmd
            self.assertEqual(cmd[cmd.index("--max_comments_count_singlenotes") + 1], "20")
            env = proc.kwargs["env"]
            self.assertEqual(env["PROMOTION_WEEK_BILI_REALTIME_DETAIL"], "1")
            self.assertEqual(env["PROMOTION_WEEK_BILI_SUBCOMMENT_ROOT_CAP"], "2")
            self.assertEqual(env["PROMOTION_WEEK_BILI_SUBCOMMENT_PAGE_CAP"], "1")

    def test_timeout_terminates_process_tree_and_rolls_back_candidate(self):
        policy.install_final_realtime_policy("bili")
        patched = crawler_runner._run_detail_comment_recovery

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out_dir = root / "out"
            out_dir.mkdir()
            stdout = root / "stdout.log"
            stderr = root / "stderr.log"

            with mock.patch(
                "monitor.final_realtime_policy.subprocess.Popen",
                side_effect=lambda cmd, **kwargs: _TimeoutPopen(cmd, **kwargs),
            ), mock.patch(
                "monitor.final_realtime_policy._terminate_process_tree"
            ) as terminate_mock, mock.patch(
                "monitor.final_realtime_policy._rollback_jsonl"
            ) as rollback_mock:
                rc, attempts = patched(
                    self._cfg(root),
                    "bili",
                    ["https://www.bilibili.com/video/av1"],
                    out_dir,
                    stdout,
                    stderr,
                    batch_size=1,
                )

            self.assertEqual(rc, 124)
            self.assertEqual(attempts, 1)
            terminate_mock.assert_called_once()
            rollback_mock.assert_called_once()
            self.assertIn(
                "process_tree_terminated=yes",
                stdout.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
