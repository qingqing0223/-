from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import tempfile
import types
import unittest
from pathlib import Path

from scripts.patch_kuaishou_creator_trial_safety import MARKER, check, patch
from monitor.creator_runner import _media_crawler_command_prefix


CLIENT_FIXTURE = '''
import asyncio
import random
from typing import Callable, Dict, List, Optional

class Logger:
    def info(self, *args, **kwargs): pass
    def error(self, *args, **kwargs): pass
class Utils:
    logger = Logger()
utils = Utils()

class KuaiShouClient:
    async def get_creator_profile(self, user_id):
        return {"visionProfile": {"userProfile": {"profile": {"user_id": user_id}}}}

    async def get_creator_info(self, user_id):
        visionProfile = await self.get_creator_profile(user_id)
        return visionProfile.get("userProfile")

    async def get_all_videos_by_creator(self, user_id: str, crawl_interval: float = 1.0, callback=None):
        result = []
        pcursor = ""
        while pcursor != "no_more":
            response = await self.get_video_by_creater_v2(user_id, pcursor)
            pcursor = response.get("pcursor", "")
            videos = response.get("feeds", [])
            result.extend(videos)
        return result
'''


CORE_FIXTURE = '''
import asyncio
from typing import Dict

class KuaishouCrawler:
    async def get_creators_and_videos(self) -> None:
        for creator_url in config.KS_CREATOR_ID_LIST:
            creator_info = parse_creator_info_from_url(creator_url)
            user_id = creator_info.user_id
            profile = await self.ks_client.get_creator_info(user_id=user_id)
            await self.ks_client.get_all_videos_by_creator(user_id=user_id)
'''


class _PagedClient:
    def __init__(self, method, pages):
        self._method = types.MethodType(method, self)
        self.pages = list(pages)
        self.calls = 0
        self.callback_sizes = []

    async def get_video_by_creater_v2(self, user_id, pcursor):
        row = self.pages[self.calls]
        self.calls += 1
        return row

    async def callback(self, rows):
        self.callback_sizes.append(len(rows))

    async def run(self, limit):
        return await self._method("account", crawl_interval=0, callback=self.callback, max_notes_count=limit)


class KuaishouCreatorTrialSafetyTests(unittest.TestCase):
    def _patched_root(self, td):
        root = Path(td)
        client = root / "media_platform/kuaishou/client.py"
        core = root / "media_platform/kuaishou/core.py"
        client.parent.mkdir(parents=True)
        client.write_text(CLIENT_FIXTURE, encoding="utf-8")
        core.write_text(CORE_FIXTURE, encoding="utf-8")
        patch(root)
        self.assertTrue(check(root)["ok"])
        return root

    def _client_method(self, root):
        spec = importlib.util.spec_from_file_location("patched_ks_client", root / "media_platform/kuaishou/client.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.KuaiShouClient.get_all_videos_by_creator

    def test_stops_at_twenty_even_when_next_page_exists(self):
        with tempfile.TemporaryDirectory() as td:
            method = self._client_method(self._patched_root(td))
            pages = [
                {"result": 1, "pcursor": "p2", "feeds": list(range(10))},
                {"result": 1, "pcursor": "p3", "feeds": list(range(10, 20))},
                {"result": 1, "pcursor": "no_more", "feeds": list(range(20, 30))},
            ]
            client = _PagedClient(method, pages)
            result = asyncio.run(client.run(20))
            self.assertEqual(len(result), 20)
            self.assertEqual(client.calls, 2)

    def test_last_page_is_sliced_to_remaining_capacity(self):
        with tempfile.TemporaryDirectory() as td:
            method = self._client_method(self._patched_root(td))
            pages = [
                {"result": 1, "pcursor": "p2", "feeds": list(range(15))},
                {"result": 1, "pcursor": "p3", "feeds": list(range(15, 30))},
            ]
            client = _PagedClient(method, pages)
            result = asyncio.run(client.run(20))
            self.assertEqual(len(result), 20)
            self.assertEqual(client.callback_sizes, [15, 5])

    def test_no_more_finishes_before_limit(self):
        with tempfile.TemporaryDirectory() as td:
            method = self._client_method(self._patched_root(td))
            client = _PagedClient(method, [{"result": 1, "pcursor": "no_more", "feeds": list(range(7))}])
            result = asyncio.run(client.run(20))
            self.assertEqual(len(result), 7)
            self.assertEqual(client.calls, 1)

    def test_non_positive_limit_keeps_full_pagination(self):
        with tempfile.TemporaryDirectory() as td:
            method = self._client_method(self._patched_root(td))
            pages = [
                {"result": 1, "pcursor": "p2", "feeds": [1, 2]},
                {"result": 1, "pcursor": "no_more", "feeds": [3, 4]},
            ]
            client = _PagedClient(method, pages)
            result = asyncio.run(client.run(0))
            self.assertEqual(result, [1, 2, 3, 4])
            self.assertEqual(client.calls, 2)

    def test_empty_profile_never_starts_post_pagination(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._patched_root(td)
            tree = ast.parse((root / "media_platform/kuaishou/core.py").read_text(encoding="utf-8"))
            method = next(
                child for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "KuaishouCrawler"
                for child in node.body if isinstance(child, ast.AsyncFunctionDef) and child.name == "get_creators_and_videos"
            )
            module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
            namespace = {
                "config": types.SimpleNamespace(KS_CREATOR_ID_LIST=["bad"], CRAWLER_MAX_SLEEP_SEC=0, CRAWLER_MAX_NOTES_COUNT=20),
                "parse_creator_info_from_url": lambda value: types.SimpleNamespace(user_id=value),
                "CreatorUrlInfo": object,
                "Dict": dict,
                "json": json,
                "utils": types.SimpleNamespace(logger=types.SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None)),
                "kuaishou_store": types.SimpleNamespace(save_creator=lambda *a, **k: None),
            }
            exec(compile(module, "patched_core", "exec"), namespace)

            class Client:
                paged = False
                async def get_creator_info(self, user_id): return {}
                async def get_all_videos_by_creator(self, **kwargs): self.paged = True; return []

            crawler = types.SimpleNamespace(ks_client=Client())
            asyncio.run(namespace["get_creators_and_videos"](crawler))
            self.assertFalse(crawler.ks_client.paged)

    def test_trial_config_is_isolated_from_formal_directory(self):
        path = Path(__file__).resolve().parents[1] / "config/kuaishou_creator_coverage.example.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        trial = r"D:\KuaishouTrial\creator_3x6j6hyt7894tag_trial"
        self.assertEqual(cfg["data_root"], trial)
        self.assertEqual(cfg["kuaishou_formal_data_root"], trial)
        self.assertEqual(cfg["crawler_max_notes_count"], 20)
        self.assertNotIn(r"D:\KuaishouTrial\20260920_real_ks", json.dumps(cfg))

    def test_creator_runner_uses_mediacrawler_venv_without_uv(self):
        with tempfile.TemporaryDirectory() as td:
            python = Path(td) / ".venv/Scripts/python.exe"
            python.parent.mkdir(parents=True)
            python.touch()
            self.assertEqual(
                _media_crawler_command_prefix(td),
                [str(python), "main.py"],
            )

    def test_profile_response_is_unwrapped_from_vision_profile(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._patched_root(td)
            spec = importlib.util.spec_from_file_location("patched_profile_client", root / "media_platform/kuaishou/client.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            client = object.__new__(module.KuaiShouClient)
            result = asyncio.run(client.get_creator_info("stable-id"))
            self.assertEqual(result["profile"]["user_id"], "stable-id")


if __name__ == "__main__":
    unittest.main()
