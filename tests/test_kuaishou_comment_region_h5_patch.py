from __future__ import annotations

from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = REPO_ROOT / "scripts" / "patch_kuaishou_comment_regions.py"


class TestKuaishouCommentRegionH5Patch(unittest.TestCase):
    def test_v6_patch_declares_public_h5_comment_fallback(self):
        text = PATCH_PATH.read_text(encoding="utf-8")
        self.assertIn('PROMOTION_WEEK_KS_COMMENT_REGION_RESTORE_V6', text)
        self.assertIn('async def _ks_h5_comment_regions', text)
        self.assertIn('async def _ks_h5_comment_fallback_response', text)
        self.assertIn('/rest/wd/photo/comment/list', text)
        self.assertIn('[KS_COMMENT_REST_BLOCKED] label=root', text)
        self.assertIn('[KS_COMMENT_REST_BLOCKED] label=sub', text)
        self.assertIn('[KS_COMMENT_H5_FETCH_FALLBACK] label=root', text)
        self.assertIn('def _ks_h5_public_comment_count', text)
        self.assertIn('subCommentsMap', text)
        self.assertIn('row["hasSubComments"] = True', text)
        self.assertIn('"commentCountV2": public_count', text)
        self.assertIn('httpx.TransportError', text)
        self.assertIn('repr(_ks_rest_exc)', text)
        self.assertIn('[KUAISHOU_COMMENT_EXCEPTION]', text)


if __name__ == "__main__":
    unittest.main()
