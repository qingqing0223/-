from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from scripts import patch_bilibili_comment_detail as patch


CORE = '''import asyncio

async def get_specified_videos(self, video_url_list):
        utils.logger.info("[BilibiliCrawler.get_specified_videos] Parsing video URLs...")
        bvids_list = []
        for video_url in video_url_list:
            try:
                video_info = parse_video_info_from_url(video_url)
                bvids_list.append(video_info.video_id)
                utils.logger.info(f"[BilibiliCrawler.get_specified_videos] Parsed video ID: {video_info.video_id} from {video_url}")
            except ValueError as e:
                utils.logger.error(f"[BilibiliCrawler.get_specified_videos] Failed to parse video URL: {e}")
                continue

        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [self.get_video_info_task(aid=0, bvid=video_id, semaphore=semaphore) for video_id in bvids_list]
        video_details = await asyncio.gather(*task_list)
'''


class BilibiliCommentDetailPatchTests(unittest.TestCase):
    def test_patch_is_idempotent_and_supports_av_aid_and_bv(self):
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
            self.assertIn('elif "/video/av" in raw_lower:', first)
            self.assertIn("parse_video_info_from_url(raw_video)", first)
            self.assertIn('self.get_video_info_task(aid=aid, bvid="", semaphore=semaphore)', first)


if __name__ == "__main__":
    unittest.main()
