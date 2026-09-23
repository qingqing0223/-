from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from scripts import patch_bilibili_realtime_discovery_bound as patch


CORE = '''import asyncio
from typing import Dict, List

class BilibiliCrawler:
    async def search_by_keywords(self):
        for keyword in ["k"]:
            page = 1
            bili_limit_count = 20
            while True:
                videos_res = await self.bili_client.search_video_by_keyword(
                    keyword=keyword,
                    page=page,
                    page_size=bili_limit_count,
                    order=SearchOrderType.DEFAULT,
                    pubtime_begin_s=0,  # Publish date start timestamp
                    pubtime_end_s=0,  # Publish date end timestamp
                )
                video_list: List[Dict] = videos_res.get("result")
                if not video_list:
                    utils.logger.info(f"[BilibiliCrawler.search_by_keywords] No more videos for '{keyword}', moving to next keyword.")
                    break

                semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
                break
'''


CORE_V2 = '''import asyncio
import os
from typing import Dict, List

class BilibiliCrawler:
    async def search_by_keywords(self):
        _bili_realtime_search = (
            os.environ.get("PROMOTION_WEEK_BILI_REALTIME_DISCOVERY", "").strip() == "1"
        )
        _bili_search_order = (
            SearchOrderType.LAST_PUBLISH
            if _bili_realtime_search
            else SearchOrderType.DEFAULT
        )
        _bili_pub_begin_s = int(
            os.environ.get("PROMOTION_WEEK_BILI_PUBTIME_BEGIN_S", "0") or 0
        )
        _bili_pub_end_s = int(
            os.environ.get("PROMOTION_WEEK_BILI_PUBTIME_END_S", "0") or 0
        )
        # PROMOTION_WEEK_BILI_REALTIME_SEARCH_WINDOW_V2
        for keyword in ["k"]:
            page = 1
            bili_limit_count = 20
            while True:
                videos_res = await self.bili_client.search_video_by_keyword(
                    keyword=keyword,
                    page=page,
                    page_size=bili_limit_count,
                    order=_bili_search_order,
                    pubtime_begin_s=_bili_pub_begin_s,
                    pubtime_end_s=_bili_pub_end_s,
                )
                video_list: List[Dict] = videos_res.get("result")
                if not video_list:
                    break

                semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
                break
'''


class BilibiliRealtimeDiscoveryBoundPatchTests(unittest.TestCase):
    def test_patch_accepts_existing_v2_window_and_adds_only_fanout(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "media_platform/bilibili"
            target.mkdir(parents=True)
            core = target / "core.py"
            core.write_text(CORE_V2, encoding="utf-8")

            patch.patch_core(root)
            first = core.read_text(encoding="utf-8")
            patch.patch_core(root)
            second = core.read_text(encoding="utf-8")

            self.assertEqual(first, second)
            ast.parse(first)
            result = patch.check(root)

            self.assertTrue(result["ok"])
            self.assertTrue(result["existing_v2_window_compatible"])
            self.assertFalse(result["owned_v3_window_compatible"])
            self.assertIn("order=_bili_search_order", first)
            self.assertIn("pubtime_begin_s=_bili_pub_begin_s", first)
            self.assertIn("pubtime_end_s=_bili_pub_end_s", first)
            self.assertIn("PROMOTION_WEEK_BILI_REALTIME_ITEMS_PER_KEYWORD", first)
            self.assertIn(
                "video_list = video_list[:_bili_realtime_items_per_keyword]",
                first,
            )

    def test_patch_is_idempotent_and_env_gated(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "media_platform/bilibili"
            target.mkdir(parents=True)
            core = target / "core.py"
            core.write_text(CORE, encoding="utf-8")

            patch.patch_core(root)
            first = core.read_text(encoding="utf-8")
            patch.patch_core(root)
            second = core.read_text(encoding="utf-8")

            self.assertEqual(first, second)
            ast.parse(first)
            result = patch.check(root)
            self.assertTrue(result["ok"])
            self.assertIn("PROMOTION_WEEK_BILI_REALTIME_DISCOVERY", first)
            self.assertIn("PROMOTION_WEEK_BILI_REALTIME_ITEMS_PER_KEYWORD", first)
            self.assertIn("PROMOTION_WEEK_BILI_PUBTIME_BEGIN_S", first)
            self.assertIn("PROMOTION_WEEK_BILI_PUBTIME_END_S", first)
            self.assertIn("SearchOrderType.LAST_PUBLISH", first)
            self.assertIn("video_list = video_list[:_bili_realtime_items_per_keyword]", first)


if __name__ == "__main__":
    unittest.main()
