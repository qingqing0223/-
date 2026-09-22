from __future__ import annotations

import ast
import asyncio
import os
import tempfile
import types
import unittest
from pathlib import Path

from pipeline.normalizer import normalize_record
from monitor.ingest import _merge_kuaishou_public_metrics
from scripts.patch_kuaishou_public_metrics import check, patch


CORE_FIXTURE = '''
import os
from typing import Dict

class DataFetchError(Exception):
    pass

class KuaishouCrawler:
    async def search(self):
        videos_res = {"feeds": []}
        video_id_list = []
        for video_detail in videos_res.get("feeds", []):
            video_id_list.append(video_detail.get("photo", {}).get("id"))
            await kuaishou_store.update_kuaishou_video(video_item=video_detail)

    async def get_video_info_task(self, video_id, semaphore):
        try:
            result = await self.ks_client.get_video_info(video_id)
            detail = result.get("visionVideoDetail")
            if not detail:
                return None
            return detail
        except DataFetchError as ex:
            return None
'''


STORE_FIXTURE = '''
from typing import Dict, List

import config

async def update_kuaishou_video(video_item: Dict):
    photo_info = video_item.get("photo", {})
    user_info = video_item.get("author", {})
    save_content_item = {
        "video_id": photo_info.get("id"),
        "nickname": user_info.get("name"),
    }
    utils.logger.info("video")
    await KuaishouStoreFactory.create_store().store_content(content_item=save_content_item)

async def update_ks_video_comment(video_id: str, comment_item: Dict):
    save_comment_item = {
        "comment_id": str(comment_item.get("comment_id") or comment_item.get("commentId")),
        "video_id": video_id,
        "content": comment_item.get("content"),
    }
    utils.logger.info("comment")
    await KuaishouStoreFactory.create_store().store_comment(comment_item=save_comment_item)
'''


class KuaishouPublicMetricsPatchTests(unittest.TestCase):
    def _root(self, td: str) -> Path:
        root = Path(td)
        core = root / "media_platform/kuaishou/core.py"
        store = root / "store/kuaishou/__init__.py"
        core.parent.mkdir(parents=True)
        store.parent.mkdir(parents=True)
        core.write_text(CORE_FIXTURE, encoding="utf-8")
        store.write_text(STORE_FIXTURE, encoding="utf-8")
        return root

    def test_patch_is_idempotent_and_wires_all_three_public_metrics(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            patch(root)
            first_core = (root / "media_platform/kuaishou/core.py").read_text(encoding="utf-8")
            first_store = (root / "store/kuaishou/__init__.py").read_text(encoding="utf-8")
            self.assertTrue(check(root)["ok"])
            patch(root)
            self.assertEqual(first_core, (root / "media_platform/kuaishou/core.py").read_text(encoding="utf-8"))
            self.assertEqual(first_store, (root / "store/kuaishou/__init__.py").read_text(encoding="utf-8"))

    def test_profile_enrichment_reads_owner_count_and_caches_by_author(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            patch(root)
            tree = ast.parse((root / "media_platform/kuaishou/core.py").read_text(encoding="utf-8"))
            method = next(
                child for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "KuaishouCrawler"
                for child in node.body if isinstance(child, ast.AsyncFunctionDef)
                and child.name == "_enrich_public_profile_metrics"
            )
            module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
            namespace = {
                "Dict": dict,
                "os": os,
                "utils": types.SimpleNamespace(
                    logger=types.SimpleNamespace(warning=lambda *a, **k: None)
                ),
            }
            exec(compile(module, "patched_core", "exec"), namespace)

            class Client:
                def __init__(self):
                    self.calls = 0

                async def get_creator_info(self, user_id):
                    self.calls += 1
                    return {"ownerCount": {"fan": 1234, "follow": 56}}

            client = Client()
            crawler = types.SimpleNamespace(ks_client=client)
            old = os.environ.get("KUAISHOU_PUBLIC_METRICS")
            os.environ["KUAISHOU_PUBLIC_METRICS"] = "1"
            try:
                first = {"author": {"id": "public-author"}, "photo": {"id": "p1"}}
                second = {"author": {"id": "public-author"}, "photo": {"id": "p2"}}
                asyncio.run(namespace["_enrich_public_profile_metrics"](crawler, first))
                asyncio.run(namespace["_enrich_public_profile_metrics"](crawler, second))
            finally:
                if old is None:
                    os.environ.pop("KUAISHOU_PUBLIC_METRICS", None)
                else:
                    os.environ["KUAISHOU_PUBLIC_METRICS"] = old

            self.assertEqual(first["author"]["follower_count"], 1234)
            self.assertEqual(first["author"]["following_count"], 56)
            self.assertEqual(second["author"]["fans_count"], 1234)
            self.assertEqual(client.calls, 1)


    def test_duplicate_observation_fills_only_missing_public_metrics(self):
        target = {
            "record_type": "comment",
            "follower_count": None,
            "following_count": None,
            "likes": None,
            "comment_reply_count": 2,
        }
        incoming = {
            "record_type": "comment",
            "follower_count": 100,
            "following_count": 8,
            "likes": 5,
            "comment_reply_count": 99,
        }
        _merge_kuaishou_public_metrics(target, incoming)
        self.assertEqual(target["follower_count"], 100)
        self.assertEqual(target["following_count"], 8)
        self.assertEqual(target["likes"], 5)
        self.assertEqual(target["comment_reply_count"], 2)

    def test_normalizer_accepts_public_kuaishou_aliases(self):
        comment = normalize_record(
            {
                "comment_id": "c1",
                "video_id": "p1",
                "content": "测试评论",
                "likedCount": "7",
            },
            source_file="comments.jsonl",
            platform_hint="ks",
        )
        self.assertEqual(comment["likes"], 7)

        video = normalize_record(
            {
                "photo_id": "p1",
                "title": "测试视频",
                "fan": "123",
                "follow": "9",
            },
            source_file="contents.jsonl",
            platform_hint="ks",
        )
        self.assertEqual(video["follower_count"], 123)
        self.assertEqual(video["following_count"], 9)


if __name__ == "__main__":
    unittest.main()
