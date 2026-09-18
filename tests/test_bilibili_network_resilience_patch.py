from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from scripts import patch_bilibili_network_resilience as patch


CLIENT = '''import asyncio
import httpx
from typing import Dict
from tools.httpx_util import make_async_client
from tools import utils

class BilibiliClient:
    def __init__(self):
        self.proxy = None
        self.timeout = 60

    async def request(self, method, url, **kwargs):
        await self._refresh_proxy_if_expired()
        async with make_async_client(proxy=self.proxy) as client:
            response = await client.request(method, url, timeout=self.timeout, **kwargs)
        try:
            data: Dict = response.json()
        except Exception:
            raise
        return data
'''


CORE = '''import asyncio
import pandas as pd

class C:
    async def get_video_info_task(self, aid: int, bvid: str, semaphore):
        async with semaphore:
            try:
                result = await self.bili_client.get_video_info(aid=aid, bvid=bvid)
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[BilibiliCrawler.get_video_info_task] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching video details {bvid or aid}")
                return result
            except DataFetchError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_video_info_task] Get video detail error: {ex}")
                return None
            except KeyError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_video_info_task] have not fund note detail video_id:{bvid}, err: {ex}")
                return None

    async def get_comments(self, video_id: str, semaphore):
        async with semaphore:
            try:
                utils.logger.info(f"[BilibiliCrawler.get_comments] begin get video_id: {video_id} comments ...")
                await self.bili_client.get_video_all_comments(video_id=video_id)
            except DataFetchError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_comments] get video_id: {video_id} comment error: {ex}")
            except Exception as e:
                utils.logger.error(f"[BilibiliCrawler.get_comments] may be been blocked, err:{e}")
                # Propagate the exception to be caught by the main loop
                raise
'''


class BilibiliNetworkResiliencePatchTests(unittest.TestCase):
    def test_patch_is_idempotent_and_syntax_valid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "media_platform/bilibili"
            target.mkdir(parents=True)
            client = target / "client.py"
            core = target / "core.py"
            client.write_text(CLIENT, encoding="utf-8")
            core.write_text(CORE, encoding="utf-8")

            patch.patch_client(root)
            patch.patch_core(root)
            first_client = client.read_text(encoding="utf-8")
            first_core = core.read_text(encoding="utf-8")

            patch.patch_client(root)
            patch.patch_core(root)
            self.assertEqual(first_client, client.read_text(encoding="utf-8"))
            self.assertEqual(first_core, core.read_text(encoding="utf-8"))

            ast.parse(first_client)
            ast.parse(first_core)
            result = patch.check(root)
            self.assertTrue(result["ok"])
            self.assertIn("for _bili_request_attempt in range(2):", first_client)
            self.assertIn("except httpx.TransportError as ex:", first_core)
            self.assertIn("BILIBILI_VIDEO_DETAIL_TRANSPORT_SKIP", first_core)
            self.assertIn("BILIBILI_COMMENT_TRANSPORT_SKIP", first_core)


if __name__ == "__main__":
    unittest.main()
