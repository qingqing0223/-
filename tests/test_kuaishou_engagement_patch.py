from pathlib import Path
import tempfile
import unittest

from pipeline.normalizer import normalize_record
from scripts.patch_kuaishou_engagement_fields import (
    MARKER,
    patch_store,
    _patch_core_detail_comment_count,
    check,
)


class KuaishouEngagementPatchTests(unittest.TestCase):
    def _store_path(self, root: Path) -> Path:
        path = root / "store" / "kuaishou" / "__init__.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _write_minimal_store(self, root: Path) -> Path:
        path = self._store_path(root)
        path.write_text(
            "import config\n"
            "from tools import utils\n"
            "from tools.user_hash import anonymize_user_id, mask_nickname\n"
            "\n"
            "class KuaishouStoreFactory:\n"
            "    @staticmethod\n"
            "    def create_store():\n"
            "        return None\n"
            "\n"
            "async def update_kuaishou_video(video_item):\n"
            "    photo_info = video_item.get(\"photo\", {})\n"
            "    video_id = photo_info.get(\"id\")\n"
            "    user_info = video_item.get(\"author\", {})\n"
            "    save_content_item = {\n"
            "        \"video_id\": video_id,\n"
            "        \"liked_count\": str(photo_info.get(\"realLikeCount\")),\n"
            "        \"viewd_count\": str(photo_info.get(\"viewCount\")),\n"
            "        \"comment_count\": str(photo_info.get(\"commentCount\") or 0),\n"
            "    }\n"
            "\n"
            "async def update_ks_video_comment(video_id, comment_item):\n"
            "    comment_id = comment_item.get(\"comment_id\")\n"
            "    save_comment_item = {\n"
            "        \"comment_id\": str(comment_id),\n"
            "        \"sub_comment_count\": str(comment_item.get(\"commentCount\") or 0),\n"
            "    }\n",
            encoding="utf-8",
        )
        return path

    def _write_minimal_core(self, root: Path) -> Path:
        path = root / "media_platform" / "kuaishou" / "core.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "class KuaishouCrawler:\n"
            "    async def get_video_info_task(self, video_id, semaphore):\n"
            "        result = await self.ks_client.get_video_info(video_id)\n"
            "        detail = result.get(\"visionVideoDetail\")\n"
            "        if detail:\n"
            "            photo = detail.get(\"photo\", {})\n"
            "            author = detail.get(\"author\", {})\n"
            "            return detail\n",
            encoding="utf-8",
        )
        return path

    def test_patch_preserves_video_and_comment_engagement_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = self._write_minimal_store(root)
            core = self._write_minimal_core(root)

            patch_store(root)
            _patch_core_detail_comment_count(root)
            once = path.read_text(encoding="utf-8")
            once_core = core.read_text(encoding="utf-8")
            patch_store(root)
            _patch_core_detail_comment_count(root)
            twice = path.read_text(encoding="utf-8")
            twice_core = core.read_text(encoding="utf-8")

            self.assertEqual(once, twice)
            self.assertEqual(once_core, twice_core)
            self.assertIn(MARKER, twice)
            self.assertIn('"realLikeCount", "likeCount", "liked_count", "like_count"', twice)
            self.assertIn('"commentCount", "commentCountV2", "commentsCount", "comment_count"', twice)
            self.assertIn('"like_count", "likeCount", "realLikeCount"', twice)
            self.assertNotIn('"comment_count": str(photo_info.get("commentCount") or 0)', twice)
            self.assertIn("PROMOTION_WEEK_KS_DETAIL_COMMENT_COUNT_V1", twice_core)
            self.assertIn("[KS_DETAIL_COMMENT_COUNT]", twice_core)
            self.assertTrue(check(root)["ok"])

    def test_normalizer_accepts_kuaishou_camel_case_video_engagement(self):
        row = normalize_record(
            {
                "platform": "ks",
                "video_id": "v1",
                "title": "test video",
                "realLikeCount": "1734",
                "commentCount": "23",
                "viewCount": "2.2万",
            }
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["likes"], 1734)
        self.assertEqual(row["comments"], 23)
        self.assertEqual(row["views"], 22000)

    def test_normalizer_accepts_kuaishou_comment_like_count(self):
        row = normalize_record(
            {
                "platform": "ks",
                "video_id": "v1",
                "comment_id": "c1",
                "content": "comment",
                "likeCount": 7,
            }
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["record_type"], "comment")
        self.assertEqual(row["likes"], 7)


if __name__ == "__main__":
    unittest.main()
