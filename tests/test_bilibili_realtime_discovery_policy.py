from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from monitor import crawler_runner


class _Proc:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode


class _PopenProc:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.pid = 12345

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode


class BilibiliRealtimeDiscoveryPolicyTests(unittest.TestCase):
    def test_realtime_bilibili_uses_platform_local_search_concurrency_and_limit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            media = root / "MediaCrawler"
            media.mkdir()
            run_root = root / "run"
            run_root.mkdir()

            cfg = {
                "keywords": ["k1", "k2"],
                "media_crawler_root": str(media),
                "login_type": "qrcode",
                "max_concurrency_num": 1,
                "get_comment": "yes",
                "get_sub_comment": "yes",
                "save_data_option": "jsonl",
                "data_root": str(root / "data"),
                "realtime_mode": True,
                "realtime_discovery_max_notes_count": 30,
            }

            with mock.patch("monitor.crawler_runner.subprocess.Popen", return_value=_PopenProc(0)) as popen_mock, \
                 mock.patch("monitor.crawler_runner.find_content_jsonl", return_value=[]), \
                 mock.patch("monitor.crawler_runner.find_comment_jsonl", return_value=[]):
                result = crawler_runner.run_platform(
                    cfg,
                    {"code": "bili", "name": "B站"},
                    run_root,
                )

            cmd = popen_mock.call_args.args[0]
            self.assertEqual(result.platform, "bili")
            self.assertIn("--crawler_max_notes_count", cmd)
            self.assertEqual(cmd[cmd.index("--crawler_max_notes_count") + 1], "20")
            self.assertIn("--max_concurrency_num", cmd)
            self.assertEqual(cmd[cmd.index("--max_concurrency_num") + 1], "4")
            env = popen_mock.call_args.kwargs["env"]
            self.assertEqual(env["PROMOTION_WEEK_BILI_REALTIME_DISCOVERY"], "1")
            self.assertEqual(env["PROMOTION_WEEK_BILI_REALTIME_ITEMS_PER_KEYWORD"], "3")

    def test_explicit_bilibili_overrides_still_win(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            media = root / "MediaCrawler"
            media.mkdir()
            run_root = root / "run"
            run_root.mkdir()

            cfg = {
                "keywords": ["k1"],
                "media_crawler_root": str(media),
                "login_type": "qrcode",
                "max_concurrency_num": 1,
                "get_comment": "no",
                "get_sub_comment": "no",
                "save_data_option": "jsonl",
                "data_root": str(root / "data"),
                "realtime_mode": True,
                "bili_realtime_discovery_max_notes_count": 40,
                "bili_realtime_search_concurrency": 3,
                "bili_realtime_items_per_keyword": 7,
            }

            with mock.patch("monitor.crawler_runner.subprocess.Popen", return_value=_PopenProc(0)) as popen_mock, \
                 mock.patch("monitor.crawler_runner.find_content_jsonl", return_value=[]), \
                 mock.patch("monitor.crawler_runner.find_comment_jsonl", return_value=[]):
                crawler_runner.run_platform(
                    cfg,
                    {"code": "bili", "name": "B站"},
                    run_root,
                )

            cmd = popen_mock.call_args.args[0]
            self.assertEqual(cmd[cmd.index("--crawler_max_notes_count") + 1], "40")
            self.assertEqual(cmd[cmd.index("--max_concurrency_num") + 1], "3")
            env = popen_mock.call_args.kwargs["env"]
            self.assertEqual(env["PROMOTION_WEEK_BILI_REALTIME_ITEMS_PER_KEYWORD"], "7")

    def test_bilibili_realtime_limits_detail_candidates_to_one_by_default(self):
        queue = {
            "version": 1,
            "items": {
                "v1": {"visible_comment_count": 10, "last_deep_crawled_at": ""},
                "v2": {"visible_comment_count": 9, "last_deep_crawled_at": ""},
            },
        }
        selected = crawler_runner._select_queue_candidates(queue, max_items=1, refresh_seconds=900)
        self.assertEqual(len(selected), 1)

    def test_non_realtime_keeps_shared_concurrency(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            media = root / "MediaCrawler"
            media.mkdir()
            run_root = root / "run"
            run_root.mkdir()

            cfg = {
                "keywords": ["k1"],
                "media_crawler_root": str(media),
                "login_type": "qrcode",
                "max_concurrency_num": 1,
                "get_comment": "no",
                "get_sub_comment": "no",
                "save_data_option": "jsonl",
                "data_root": str(root / "data"),
                "realtime_mode": False,
                "crawler_max_notes_count": 20,
                "bili_realtime_search_concurrency": 4,
            }

            with mock.patch("monitor.crawler_runner.subprocess.run", return_value=_Proc(0)) as run_mock, \
                 mock.patch("monitor.crawler_runner.find_content_jsonl", return_value=[]), \
                 mock.patch("monitor.crawler_runner.find_comment_jsonl", return_value=[]):
                crawler_runner.run_platform(
                    cfg,
                    {"code": "bili", "name": "B站"},
                    run_root,
                )

            cmd = run_mock.call_args.args[0]
            self.assertEqual(cmd[cmd.index("--max_concurrency_num") + 1], "1")


if __name__ == "__main__":
    unittest.main()
