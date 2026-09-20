from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import monitor.crawler_runner as crawler_runner
from monitor.unknown_comment_queue_policy import install_unknown_comment_count_fallback


class UnknownCommentQueueFallbackTests(unittest.TestCase):
    def setUp(self):
        self.original_update = crawler_runner._update_queue_from_content

    def tearDown(self):
        crawler_runner._update_queue_from_content = self.original_update
        for platform in ("xhs", "bili", "wb", "toutiao", "zhihu"):
            marker = f"_promotion_week_unknown_comment_fallback_{platform}"
            if hasattr(crawler_runner, marker):
                delattr(crawler_runner, marker)

    def _exercise(self, platform: str, row: dict) -> dict:
        install_unknown_comment_count_fallback(platform)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "search_contents.jsonl"
            path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            queue = {"version": 1, "items": {}}
            crawler_runner._update_queue_from_content(platform, [path], queue)
            self.assertEqual(len(queue["items"]), 1)
            return next(iter(queue["items"].values()))

    def test_unknown_count_is_queue_only_signal(self):
        fixtures = {
            "xhs": {"note_id": "x1", "comment_count": 0},
            "bili": {"video_id": "b1", "comment_count": 0},
            "wb": {"note_id": "w1", "comment_count": 0},
            "toutiao": {
                "article_id": "t1",
                "content_id": "t1",
                "content_url": "https://www.toutiao.com/article/1/",
                "comment_count": 0,
            },
            "zhihu": {"content_id": "z1", "comment_count": 0},
        }
        for platform, row in fixtures.items():
            with self.subTest(platform=platform):
                item = self._exercise(platform, row)
                self.assertEqual(item["visible_comment_count"], 1)
                self.assertTrue(item["comment_count_unknown"])
                self.assertEqual(item["queue_signal"], f"{platform}_unknown_comment_count")

    def test_real_visible_count_is_preserved(self):
        item = self._exercise("xhs", {"note_id": "x2", "comment_count": 17})
        self.assertEqual(item["visible_comment_count"], 17)
        self.assertFalse(item["comment_count_unknown"])
        self.assertEqual(item["queue_signal"], "visible_comment_count")


if __name__ == "__main__":
    unittest.main()
