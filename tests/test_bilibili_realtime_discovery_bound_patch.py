from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from scripts import patch_bilibili_realtime_discovery_bound as patch


CORE = '''import asyncio
from typing import Dict, List

async def search_by_keywords(self):
    keyword = "k"
    video_list: List[Dict] = []
    if not video_list:
        utils.logger.info(f"[BilibiliCrawler.search_by_keywords] No more videos for '{keyword}', moving to next keyword.")
        break

    semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
'''


class BilibiliRealtimeDiscoveryBoundPatchTests(unittest.TestCase):
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
            self.assertIn("video_list = video_list[:_bili_realtime_items_per_keyword]", first)


if __name__ == "__main__":
    unittest.main()
