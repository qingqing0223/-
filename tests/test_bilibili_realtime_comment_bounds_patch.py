from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from scripts import patch_bilibili_realtime_comment_bounds as patch


CLIENT = '''import asyncio
import json
from typing import Dict, List

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
        while not is_end:
            comment_list = []
            if is_fetch_sub_comments:
                for comment in comment_list:
                    comment_id = comment['rpid']
                    if (comment.get("rcount", 0) > 0):
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

    async def get_video_all_level_two_comments(
        self,
        video_id: str,
        level_one_comment_id: int,
        order_mode,
        ps: int = 10,
        crawl_interval: float = 1.0,
        callback=None,
    ) -> Dict:
        pn = 1
        while True:
            result = await self.get_video_level_two_comments(video_id, level_one_comment_id, pn, ps, order_mode)
            comment_list: List[Dict] = result.get("replies", [])
            if callback:  # If there is a callback function, execute it
                await callback(video_id, comment_list)
            await asyncio.sleep(crawl_interval)
            if (int(result["page"]["count"]) <= pn * ps):
                break

            pn += 1
'''


class BilibiliRealtimeCommentBoundsPatchTests(unittest.TestCase):
    def test_patch_is_idempotent_and_preserves_non_realtime_mode(self):
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
            self.assertIn("PROMOTION_WEEK_BILI_REALTIME_DETAIL", first)
            self.assertIn("PROMOTION_WEEK_BILI_SUBCOMMENT_ROOT_CAP", first)
            self.assertIn("PROMOTION_WEEK_BILI_SUBCOMMENT_PAGE_CAP", first)
            self.assertIn("and _bili_subcomment_root_cap > 0", first)
            self.assertIn("and _bili_subcomment_page_cap > 0", first)


if __name__ == "__main__":
    unittest.main()
