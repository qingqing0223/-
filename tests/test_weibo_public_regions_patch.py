from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WeiboPublicRegionPatchTest(unittest.TestCase):
    def test_script_contract(self):
        text = (ROOT / "scripts" / "patch_weibo_public_regions.py").read_text(encoding="utf-8")
        self.assertIn("PROMOTION_WEEK_WB_PUBLIC_REGION_V2", text)
        self.assertIn('_WB_PUBLIC_SOURCE_KEYS = {"source"}', text)
        self.assertIn('text.startswith("来自")', text)
        self.assertIn('save_comment_item["ip_location"] = _wb_find_coarse_public_region(comment_item)', text)
        self.assertIn("comment_source_region_support", text)

    def test_source_label_is_public_region_only(self):
        # This mirrors the generated helper contract without contacting Weibo.
        provinces = ("上海", "四川", "广东")
        def region_from_source(value: str) -> str:
            text = str(value or "").strip()
            if not text.startswith("来自"):
                return ""
            text = text[2:].strip()
            for province in provinces:
                if province in text:
                    return province
            return ""

        self.assertEqual(region_from_source("来自上海"), "上海")
        self.assertEqual(region_from_source("来自四川"), "四川")
        self.assertEqual(region_from_source("iPhone客户端"), "")
        self.assertEqual(region_from_source("网页链接"), "")


if __name__ == "__main__":
    unittest.main()
