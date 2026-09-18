from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = REPO_ROOT / "scripts" / "patch_kuaishou_comment_regions.py"


def load_patch_module():
    spec = importlib.util.spec_from_file_location("ks_region_patch", PATCH_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


V3_CLIENT = '''from tools import utils\nfrom tools.public_region import coarse_public_region  # PROMOTION_WEEK_KS_COMMENT_REGION_RESTORE_V3\n\ndef _ks_direct_public_region(obj):\n    return coarse_public_region(obj.get(\"authorArea\")) if isinstance(obj, dict) else \"\"\n\ndef _ks_enrich_comment_regions(response, comments):\n    return 0\n\ndef _ks_merge_region_by_comment_id(target_comments, supplemental_comments):\n    return 0\n\ndef _ks_comment_region_debug(response, comments, label):\n    utils.logger.info(\"[KS_COMMENT_REGION_DEBUG]\")\n\nclass KuaiShouClient:\n    async def get_video_comments(self, photo_id, pcursor=\"\"):\n        result = await self.request_rest_v2(\"/rest/v/photo/comment/list\", {\"photoId\": photo_id, \"pcursor\": pcursor})\n        _ks_root_comments = result.get(\"rootCommentsV2\", [])\n        if _ks_root_comments:\n            try:\n                _ks_supplemental = await _ks_graphql_root_regions(self, photo_id, pcursor)\n                _ks_merged = _ks_merge_region_by_comment_id(_ks_root_comments, _ks_supplemental)\n                utils.logger.info(f\"[KS_COMMENT_REGION_GRAPHQL] label=root merged={_ks_merged}\")\n            except Exception as _ks_region_exc:\n                utils.logger.info(f\"[KS_COMMENT_REGION_GRAPHQL_FAILED] label=root type={type(_ks_region_exc).__name__}\")\n        return result\n\n    async def get_video_sub_comments(self, photo_id, root_comment_id, pcursor=\"\"):\n        result = await self.request_rest_v2(\"/rest/v/photo/comment/sublist\", {\"photoId\": photo_id, \"pcursor\": pcursor, \"rootCommentId\": root_comment_id})\n        _ks_sub_comments = result.get(\"subCommentsV2\", [])\n        if _ks_sub_comments:\n            try:\n                _ks_supplemental = await _ks_graphql_sub_regions(self, photo_id, root_comment_id, pcursor)\n                _ks_merged = _ks_merge_region_by_comment_id(_ks_sub_comments, _ks_supplemental)\n                utils.logger.info(f\"[KS_COMMENT_REGION_GRAPHQL] label=sub merged={_ks_merged}\")\n            except Exception as _ks_region_exc:\n                utils.logger.info(f\"[KS_COMMENT_REGION_GRAPHQL_FAILED] label=sub type={type(_ks_region_exc).__name__}\")\n        return result\n\n    async def get_video_all_comments(self):\n        comments_res = {}\n        comments = comments_res.get(\"rootCommentsV2\", [])\n        _ks_root_region_count = _ks_enrich_comment_regions(comments_res, comments)  # PROMOTION_WEEK_KS_COMMENT_REGION_RESTORE_V3\n        sub_comments = comments_res.get(\"subCommentsV2\", [])\n        _ks_sub_region_count = _ks_enrich_comment_regions(comments_res, sub_comments)  # PROMOTION_WEEK_KS_COMMENT_REGION_RESTORE_V3\n'''


class TestKuaishouCommentRegionH5Patch(unittest.TestCase):
    def test_v3_client_upgrades_to_h5_without_legacy_graphql_calls(self):
        patch = load_patch_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = root / "media_platform" / "kuaishou" / "client.py"
            client.parent.mkdir(parents=True)
            client.write_text(V3_CLIENT, encoding="utf-8")

            patch.patch_client(root)
            status = patch.check(root)
            text = client.read_text(encoding="utf-8")

            self.assertTrue(status["ok"], status)
            self.assertIn("PROMOTION_WEEK_KS_COMMENT_REGION_RESTORE_V5", text)
            self.assertIn("async def _ks_h5_comment_regions", text)
            self.assertIn("/rest/wd/photo/comment/list", text)
            self.assertIn("await _ks_h5_comment_regions(self, photo_id)", text)
            self.assertIn("async def _ks_h5_comment_fallback_response", text)
            self.assertIn("[KS_COMMENT_REST_BLOCKED] label=root", text)
            self.assertIn("[KS_COMMENT_H5_FETCH_FALLBACK] label=root", text)
            self.assertNotIn("await _ks_graphql_root_regions(", text)
            self.assertNotIn("await _ks_graphql_sub_regions(", text)


if __name__ == "__main__":
    unittest.main()
