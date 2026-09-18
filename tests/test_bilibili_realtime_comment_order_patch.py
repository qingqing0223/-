from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from scripts import patch_bilibili_realtime_comment_order as patch


CLIENT = '''import asyncio
import json
from typing import Dict, List

from .field import CommentOrderType

class BilibiliClient:
    async def get_video_all_comments(
        self,
        video_id: str,
        crawl_interval: float = 1.0,
        is_fetch_sub_comments=False,
        callback=None,
        max_count: int = 10,
    ):
        result = []
        is_end = False
        next_page = 0
        max_retries = 3
        is_first_page = True
        while not is_end and len(result) < max_count:
            comments_res = None
            for attempt in range(max_retries):
                try:
                    comments_res = await self.get_video_comments(video_id, CommentOrderType.DEFAULT, next_page)
                    break
                except Exception:
                    raise
            comment_list: List[Dict] = comments_res.get("replies") or []
            if is_fetch_sub_comments:
                for comment in comment_list:
                    comment_id = comment['rpid']
                    if comment.get("rcount", 0) > 0:
                        await self.get_video_all_level_two_comments(
                            video_id,
                            comment_id,
                            CommentOrderType.DEFAULT,
                            10,
                            crawl_interval,
                            callback,
                        )
            is_end = True
        return result
'''


class BilibiliRealtimeCommentOrderPatchTests(unittest.TestCase):
    def test_patch_is_idempotent_and_realtime_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "media_platform/bilibili"
            target.mkdir(parents=True)
            client = target / "client.py"
            client.write_text(CLIENT, encoding="utf-8")

            patch.patch_client(root)
            first = client.read_text(encoding="utf-8")
            patch.patch_client(root)
            second = client.read_text(encoding="utf-8")

            self.assertEqual(first, second)
            ast.parse(first)
            result = patch.check(root)
            self.assertTrue(result["ok"])
            self.assertIn("CommentOrderType.TIME", first)
            self.assertIn("PROMOTION_WEEK_BILI_REALTIME_DETAIL", first)
            self.assertIn("else CommentOrderType.DEFAULT", first)
            self.assertIn("_bili_realtime_comment_order", first)


if __name__ == "__main__":
    unittest.main()
