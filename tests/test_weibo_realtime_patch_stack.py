from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WeiboRealtimePatchStackTest(unittest.TestCase):
    def test_realtime_resilience_contract(self):
        text = (ROOT / "scripts" / "patch_weibo_realtime_resilience.py").read_text(encoding="utf-8")
        self.assertIn("PROMOTION_WEEK_WB_REALTIME_RESILIENCE_V3", text)
        self.assertIn("WEIBO_VERIFY_REQUIRED", text)
        self.assertIn("stop_after_attempt(2)", text)
        self.assertIn("timeout=25", text)
        self.assertIn("PROMOTION_WEEK_WB_REALTIME", text)
        self.assertIn('wait_until="domcontentloaded"', text)

    def test_comment_hierarchy_contract(self):
        text = (ROOT / "scripts" / "patch_weibo_comment_hierarchy.py").read_text(encoding="utf-8")
        self.assertIn("PROMOTION_WEEK_WB_COMMENT_HIERARCHY_V2", text)
        self.assertIn('["parent_comment_id"] = ""', text)
        self.assertIn('["root_comment_id"]', text)
        self.assertIn('body = payload.get("data")', text)
        self.assertIn('isinstance(body, dict)', text)
        self.assertIn('next_max_id = body.get(', text)
        self.assertIn('next_max_id_type = body.get(', text)
        self.assertNotIn("WB_CHILD_DEBUG", text)
        self.assertNotIn("WB_ROOT_DEBUG", text)

    def test_public_region_contract(self):
        text = (ROOT / "scripts" / "patch_weibo_public_regions.py").read_text(encoding="utf-8")
        self.assertIn("PROMOTION_WEEK_WB_PUBLIC_REGION_V2", text)
        self.assertIn("def _wb_find_coarse_public_region", text)
        self.assertIn('"region_name"', text)
        self.assertNotIn('"_WB_PUBLIC_REGION_KEYS = {"location"', text)

    def test_student_upgrade_deploys_all_weibo_patches(self):
        text = (ROOT / "scripts" / "final_student_update_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("patch_weibo_realtime_resilience.py", text)
        self.assertIn("patch_weibo_comment_hierarchy.py", text)
        self.assertIn("patch_weibo_public_regions.py", text)
        self.assertIn("patch_weibo_public_identity.py", text)

    def test_runner_has_weibo_realtime_bounds(self):
        runner = (ROOT / "run_single_platform.py").read_text(encoding="utf-8")
        crawler = (ROOT / "monitor" / "crawler_runner.py").read_text(encoding="utf-8")
        self.assertIn('args.platform == "wb"', runner)
        self.assertIn('"wb_realtime_detail_max_items_per_cycle"', runner)
        self.assertIn('"wb_realtime_search_timeout_seconds"', runner)
        self.assertIn('"wb_realtime_discovery_max_notes_count"] = 10', runner)
        self.assertIn('"PROMOTION_WEEK_WB_REALTIME"', crawler)
        self.assertIn('"weibo_verify_required"', crawler.lower())


if __name__ == "__main__":
    unittest.main()
