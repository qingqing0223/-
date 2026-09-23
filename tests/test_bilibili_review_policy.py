from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from monitor import crawler_runner
from monitor.bilibili_policy import is_bilibili_campaign_relevant
from monitor.campaign_scope import CORE_KEYWORDS, all_search_queries, select_realtime_queries
from monitor.unknown_comment_queue_policy import install_unknown_comment_count_fallback
from scripts.patch_bilibili_realtime_discovery_bound import check, patch_core


class BilibiliReviewPolicyTests(unittest.TestCase):
    def test_topic_gate_accepts_formal_campaign_and_rejects_unrelated_week(self):
        self.assertTrue(is_bilibili_campaign_relevant({
            "title": "2026年民族团结进步宣传周主场活动",
        }))
        self.assertTrue(is_bilibili_campaign_relevant({
            "title": "石榴花开",
            "desc": "铸牢中华民族共同体意识",
        }))
        self.assertFalse(is_bilibili_campaign_relevant({
            "title": "国家网络安全宣传周启动",
            "source_keyword": "民族团结进步宣传周",
        }))
        self.assertFalse(is_bilibili_campaign_relevant({
            "title": "普通美食探店",
            "source_keyword": "民族团结进步宣传周",
        }))

    def test_new_keyword_policy_search_broad_admission_strict(self):
        self.assertEqual(len(CORE_KEYWORDS), 11)
        expanded = all_search_queries()
        self.assertGreater(len(expanded), len(CORE_KEYWORDS))
        self.assertIn("民族团结宣传周", expanded)
        self.assertIn("民族团结进取宣传周", expanded)
        self.assertIn("民族团结进步 主题宣传片", expanded)
        self.assertIn("石榴花开 宣传周", expanded)

        self.assertTrue(is_bilibili_campaign_relevant({
            "title": "民族团结进步宣传周主题宣传片发布",
        }))
        self.assertTrue(is_bilibili_campaign_relevant({
            "title": "民族团结宣传周主场活动",
        }))
        self.assertTrue(is_bilibili_campaign_relevant({
            "title": "石榴花开",
            "desc": "2026年9月21日民族团结进步宣传周相关活动",
        }))

        self.assertFalse(is_bilibili_campaign_relevant({
            "title": "石榴花开",
            "desc": "铸牢中华民族共同体意识日常宣传",
        }))
        self.assertFalse(is_bilibili_campaign_relevant({
            "title": "2025年民族团结进步宣传周回顾",
        }))
        self.assertFalse(is_bilibili_campaign_relevant({
            "title": "民族团结进步宣传月活动",
        }))

        realtime = select_realtime_queries(
            expanded,
            supplemental_count=5,
            bucket=0,
        )
        for keyword in CORE_KEYWORDS:
            self.assertIn(keyword, realtime)
        self.assertLess(len(realtime), len(expanded))

    def test_bili_explicit_zero_is_not_promoted_to_unknown_probe(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "search_contents.jsonl"
            rows = [
                {
                    "video_id": "BV-zero",
                    "title": "民族团结进步宣传周",
                    "comment_count": 0,
                },
                {
                    "video_id": "BV-missing",
                    "title": "民族团结进步宣传周",
                },
                {
                    "video_id": "BV-positive",
                    "title": "民族团结进步宣传周",
                    "comment_count": 3,
                },
            ]
            path.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            original = crawler_runner._update_queue_from_content
            marker = "_promotion_week_unknown_comment_fallback_bili"
            if hasattr(crawler_runner, marker):
                delattr(crawler_runner, marker)
            try:
                install_unknown_comment_count_fallback("bili")
                queue = {"version": 1, "items": {}}
                crawler_runner._update_queue_from_content("bili", [path], queue)
                items = queue["items"]

                self.assertEqual(items["BV-zero"]["visible_comment_count"], 0)
                self.assertEqual(
                    items["BV-zero"]["queue_signal"],
                    "explicit_zero_comment_count",
                )
                self.assertEqual(items["BV-missing"]["visible_comment_count"], 1)
                self.assertTrue(items["BV-missing"]["comment_count_unknown"])
                self.assertEqual(items["BV-positive"]["visible_comment_count"], 3)
                self.assertFalse(items["BV-positive"]["comment_count_unknown"])
            finally:
                crawler_runner._update_queue_from_content = original
                if hasattr(crawler_runner, marker):
                    delattr(crawler_runner, marker)

    def test_realtime_patch_adds_pubdate_window_and_remains_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = root / "media_platform" / "bilibili" / "core.py"
            core.parent.mkdir(parents=True, exist_ok=True)
            core.write_text(
                "import asyncio\n"
                "from .field import SearchOrderType\n"
                "class BilibiliCrawler:\n"
                "    async def search_by_keywords(self):\n"
                "        bili_limit_count = 20\n"
                "        keyword = 'k'\n"
                "        page = 1\n"
                "        video_list = []\n"
                "        videos_res = await self.bili_client.search_video_by_keyword(\n"
                "            keyword=keyword,\n"
                "            page=page,\n"
                "            page_size=bili_limit_count,\n"
                "            order=SearchOrderType.DEFAULT,\n"
                "            pubtime_begin_s=0,  # Publish date start timestamp\n"
                "            pubtime_end_s=0,  # Publish date end timestamp\n"
                "        )\n"
                "        video_list = videos_res.get('result')\n"
                "        if not video_list:\n"
                "            utils.logger.info(f\"[BilibiliCrawler.search_by_keywords] No more videos for '{keyword}', moving to next keyword.\")\n"
                "            return\n"
                "        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)\n",
                encoding="utf-8",
            )

            patch_core(root)
            once = core.read_text(encoding="utf-8")
            patch_core(root)
            twice = core.read_text(encoding="utf-8")

            self.assertEqual(once, twice)
            self.assertIn("PROMOTION_WEEK_BILI_SEARCH_ORDER", twice)
            self.assertIn("PROMOTION_WEEK_BILI_PUBTIME_BEGIN_S", twice)
            self.assertIn("SearchOrderType.LAST_PUBLISH", twice)
            self.assertIn("PROMOTION_WEEK_BILI_REALTIME_ITEMS_PER_KEYWORD", twice)
            self.assertTrue(check(root)["ok"])


if __name__ == "__main__":
    unittest.main()
