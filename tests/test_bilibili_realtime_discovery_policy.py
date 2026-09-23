from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from monitor import crawler_runner


class _Proc:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode


class BilibiliRealtimeDiscoveryPolicyTests(unittest.TestCase):
    def test_realtime_content_and_comment_candidates_are_independent(self):
        with tempfile.TemporaryDirectory() as td:
            content_file = Path(td) / "search_contents.jsonl"
            rows = [
                {
                    "video_id": "BV-zero-1",
                    "create_time": "2026-09-21T10:00:00+08:00",
                    "title": "民族团结进步宣传周主题宣传片（一）",
                    "comment_count": 0,
                    "tags": ["民族团结", "宣传周"],
                },
                {
                    "video_id": "BV-zero-2",
                    "create_time": "2026-09-22T12:00:00+08:00",
                    "title": "民族团结进步宣传周主题宣传片（二）",
                    "comment_count": 0,
                    "tags": ["主题活动"],
                },
                {
                    "video_id": "BV-comments",
                    "create_time": "2026-09-23T15:00:00+08:00",
                    "title": "民族团结进步宣传周主场活动",
                    "comment_count": 4,
                    "tags": ["主场活动"],
                },
                {
                    "video_id": "BV-comments",
                    "create_time": "2026-09-23T15:00:00+08:00",
                    "title": "民族团结进步宣传周主场活动",
                    "comment_count": 4,
                },
                {
                    "video_id": "BV-noise",
                    "create_time": "2026-09-23T16:00:00+08:00",
                    "title": "普通美食探店视频",
                    "comment_count": 99,
                    "tags": ["美食"],
                },
            ]
            content_file.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            content_candidates = crawler_runner._bili_content_discovery_candidates(
                [content_file]
            )
            queue = {"version": 1, "items": {}}
            crawler_runner._update_queue_from_content("bili", [content_file], queue)
            comment_candidates = crawler_runner._select_queue_candidates(
                queue, max_items=10, refresh_seconds=900
            )

            self.assertEqual(
                content_candidates,
                ["BV-zero-1", "BV-zero-2", "BV-comments"],
            )
            self.assertEqual(comment_candidates, ["BV-comments"])
            self.assertNotIn("BV-noise", queue["items"])

    def test_bilibili_content_detail_disables_comment_crawling(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stdout = root / "stdout.log"
            stderr = root / "stderr.log"
            output = root / "output"
            output.mkdir()
            cfg = {
                "media_crawler_root": str(root),
                "login_type": "qrcode",
                "max_concurrency_num": 2,
                "save_data_option": "jsonl",
            }

            with mock.patch(
                "monitor.crawler_runner.subprocess.run", return_value=_Proc(0)
            ) as run_mock:
                rc, batches = crawler_runner._run_bili_content_detail_discovery(
                    cfg,
                    ["BV-zero-1", "BV-zero-2", "BV-comments"],
                    output,
                    stdout,
                    stderr,
                )

            self.assertEqual((rc, batches), (0, 1))
            cmd = run_mock.call_args.args[0]
            self.assertEqual(
                cmd[cmd.index("--specified_id") + 1],
                "BV-zero-1,BV-zero-2,BV-comments",
            )
            self.assertEqual(cmd[cmd.index("--get_comment") + 1], "no")
            self.assertEqual(cmd[cmd.index("--get_sub_comment") + 1], "no")

    def test_realtime_main_flow_details_all_content_but_only_comments_one(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            media = root / "MediaCrawler"
            media.mkdir()
            run_root = root / "run"
            run_root.mkdir()
            content_file = root / "search_contents.jsonl"
            rows = [
                {
                    "video_id": "BV-zero-1",
                    "create_time": "2026-09-21T10:00:00+08:00",
                    "title": "民族团结进步宣传周主题宣传片（一）",
                    "comment_count": 0,
                },
                {
                    "video_id": "BV-zero-2",
                    "create_time": "2026-09-22T12:00:00+08:00",
                    "title": "民族团结进步宣传周主题宣传片（二）",
                    "comment_count": 0,
                },
                {
                    "video_id": "BV-comments",
                    "create_time": "2026-09-23T15:00:00+08:00",
                    "title": "民族团结进步宣传周主场活动",
                    "comment_count": 4,
                },
                {
                    "video_id": "BV-noise",
                    "create_time": "2026-09-23T16:00:00+08:00",
                    "title": "普通美食探店视频",
                    "comment_count": 99,
                },
            ]
            content_file.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )
            cfg = {
                "keywords": ["民族团结进步宣传周"],
                "media_crawler_root": str(media),
                "login_type": "qrcode",
                "max_concurrency_num": 1,
                "get_comment": "yes",
                "get_sub_comment": "yes",
                "save_data_option": "jsonl",
                "data_root": str(root / "data"),
                "realtime_mode": True,
            }

            with mock.patch(
                "monitor.crawler_runner.subprocess.run", return_value=_Proc(0)
            ), mock.patch(
                "monitor.crawler_runner.find_content_jsonl",
                return_value=[content_file],
            ), mock.patch(
                "monitor.crawler_runner.find_comment_jsonl", return_value=[]
            ), mock.patch(
                "monitor.crawler_runner._run_bili_content_detail_discovery",
                return_value=(0, 1),
            ) as content_detail, mock.patch(
                "monitor.crawler_runner._run_detail_comment_recovery",
                return_value=(0, 1),
            ) as comment_detail:
                crawler_runner.run_platform(
                    cfg,
                    {"code": "bili", "name": "B站"},
                    run_root,
                )

            self.assertEqual(
                content_detail.call_args.args[1],
                ["BV-zero-1", "BV-zero-2", "BV-comments"],
            )
            self.assertEqual(comment_detail.call_args.args[2], ["BV-comments"])

    def test_relevant_zero_comment_video_remains_a_discovery_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            content_file = Path(td) / "search_contents.jsonl"
            rows = [
                {
                    "video_id": "BV-related-zero",
                    "create_time": "2026-09-21T09:00:00+08:00",
                    "title": "2026年民族团结进步宣传周主题宣传片",
                    "comment_count": 0,
                    "tags": ["民族团结", "宣传周"],
                },
                {
                    "video_id": "BV-unrelated",
                    "create_time": "2026-09-23T16:00:00+08:00",
                    "title": "普通美食探店视频",
                    "comment_count": 12,
                    "tags": ["美食"],
                },
            ]
            content_file.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            discovered = crawler_runner._detail_recovery_candidates(
                "bili", [content_file], max_items=1
            )

            self.assertEqual(discovered, ["BV-related-zero"])

    def test_bilibili_comment_recovery_still_requires_visible_comments(self):
        with tempfile.TemporaryDirectory() as td:
            content_file = Path(td) / "search_contents.jsonl"
            rows = [
                {
                    "video_id": "BV-zero",
                    "create_time": "2026-09-21T09:00:00+08:00",
                    "title": "民族团结进步宣传周",
                    "comment_count": 0,
                },
                {
                    "video_id": "BV-comments",
                    "create_time": "2026-09-22T12:00:00+08:00",
                    "title": "民族团结进步宣传周",
                    "comment_count": 3,
                },
            ]
            content_file.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )
            discovered = crawler_runner._detail_recovery_candidates(
                "bili", [content_file], max_items=1
            )

            comment_candidates = crawler_runner._comment_recovery_candidates(
                "bili", [content_file], discovered, max_items=1
            )

            self.assertEqual(discovered, ["BV-zero", "BV-comments"])
            self.assertEqual(comment_candidates, ["BV-comments"])

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

            with mock.patch("monitor.crawler_runner.subprocess.run", return_value=_Proc(0)) as run_mock, \
                 mock.patch("monitor.crawler_runner.find_content_jsonl", return_value=[]), \
                 mock.patch("monitor.crawler_runner.find_comment_jsonl", return_value=[]):
                result = crawler_runner.run_platform(
                    cfg,
                    {"code": "bili", "name": "B站"},
                    run_root,
                )

            cmd = run_mock.call_args.args[0]
            self.assertEqual(result.platform, "bili")
            self.assertIn("--crawler_max_notes_count", cmd)
            self.assertEqual(cmd[cmd.index("--crawler_max_notes_count") + 1], "100")
            self.assertIn("--max_concurrency_num", cmd)
            self.assertEqual(cmd[cmd.index("--max_concurrency_num") + 1], "4")
            env = run_mock.call_args.kwargs["env"]
            self.assertEqual(env["PROMOTION_WEEK_BILI_REALTIME_DISCOVERY"], "1")
            self.assertEqual(env["PROMOTION_WEEK_BILI_REALTIME_ITEMS_PER_KEYWORD"], "20")
            self.assertEqual(env["PROMOTION_WEEK_BILI_SEARCH_ORDER"], "pubdate")
            self.assertEqual(
                env["PROMOTION_WEEK_BILI_EFFECTIVE_START_TIME"],
                "2026-09-21T09:00:00+08:00",
            )

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

            with mock.patch("monitor.crawler_runner.subprocess.run", return_value=_Proc(0)) as run_mock, \
                 mock.patch("monitor.crawler_runner.find_content_jsonl", return_value=[]), \
                 mock.patch("monitor.crawler_runner.find_comment_jsonl", return_value=[]):
                crawler_runner.run_platform(
                    cfg,
                    {"code": "bili", "name": "B站"},
                    run_root,
                )

            cmd = run_mock.call_args.args[0]
            self.assertEqual(cmd[cmd.index("--crawler_max_notes_count") + 1], "100")
            self.assertEqual(cmd[cmd.index("--max_concurrency_num") + 1], "3")
            env = run_mock.call_args.kwargs["env"]
            self.assertEqual(env["PROMOTION_WEEK_BILI_REALTIME_ITEMS_PER_KEYWORD"], "20")

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
