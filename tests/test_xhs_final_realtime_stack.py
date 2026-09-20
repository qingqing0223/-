from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class XhsFinalRealtimeStackTest(unittest.TestCase):
    def test_resilience_patch_contract(self):
        text = (ROOT / "scripts" / "patch_xhs_realtime_resilience.py").read_text(encoding="utf-8")
        self.assertIn("PROMOTION_WEEK_XHS_REALTIME_RESILIENCE_V1", text)
        self.assertIn("XHS_VERIFY_REQUIRED", text)
        self.assertIn('wait_until="domcontentloaded", timeout=20000', text)
        self.assertIn("PROMOTION_WEEK_XHS_REALTIME_DISCOVERY", text)
        self.assertIn("PROMOTION_WEEK_XHS_REALTIME_ITEMS_PER_KEYWORD", text)

    def test_comment_hierarchy_contract(self):
        text = (ROOT / "scripts" / "patch_xhs_comment_hierarchy.py").read_text(encoding="utf-8")
        self.assertIn("PROMOTION_WEEK_XHS_COMMENT_HIERARCHY_V1", text)
        self.assertIn('["parent_comment_id"] = ""', text)
        self.assertIn('["root_comment_id"]', text)
        self.assertIn("_promotion_week_xhs_paged_sub", text)

    def test_public_region_contract(self):
        text = (ROOT / "scripts" / "patch_xhs_public_regions.py").read_text(encoding="utf-8")
        self.assertIn("PROMOTION_WEEK_XHS_PUBLIC_REGION_V1", text)
        self.assertIn("def _xhs_find_coarse_public_region", text)
        self.assertIn('"ip_location"', text)
        self.assertIn("public_region_probe", text)
        self.assertNotIn('"_XHS_PUBLIC_REGION_KEYS = {\n    \"location\"', text)

    def test_student_upgrade_deploys_all_xhs_patches(self):
        text = (ROOT / "scripts" / "final_student_update_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("patch_xhs_realtime_resilience.py", text)
        self.assertIn("patch_xhs_comment_hierarchy.py", text)
        self.assertIn("patch_xhs_public_regions.py", text)

    def test_runtime_has_xhs_bounds(self):
        runner = (ROOT / "run_single_platform.py").read_text(encoding="utf-8")
        crawler = (ROOT / "monitor" / "crawler_runner.py").read_text(encoding="utf-8")
        policy = (ROOT / "monitor" / "final_realtime_policy.py").read_text(encoding="utf-8")
        self.assertIn('args.platform == "xhs"', runner)
        self.assertIn('"xhs_realtime_search_timeout_seconds"', runner)
        self.assertIn("XHS_REALTIME_SEARCH_TIMEOUT", crawler)
        self.assertIn("PROMOTION_WEEK_XHS_REALTIME_DISCOVERY", crawler)
        self.assertIn("_REALTIME_ACCESS_GUARD_STOP", policy)
        self.assertIn('platform in {"wb", "xhs", "toutiao"}', policy)


if __name__ == "__main__":
    unittest.main()
