from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TiebaFinalRealtimeStackTest(unittest.TestCase):
    def test_realtime_patch_contract(self):
        text = (ROOT / "scripts" / "patch_tieba_realtime_resilience.py").read_text(encoding="utf-8")
        self.assertIn("PROMOTION_WEEK_TIEBA_REALTIME_RESILIENCE_V1", text)
        self.assertIn("PROMOTION_WEEK_TIEBA_REALTIME_DISCOVERY", text)
        self.assertIn("PROMOTION_WEEK_TIEBA_REALTIME_ITEMS_PER_KEYWORD", text)
        self.assertIn("PROMOTION_WEEK_TIEBA_SUBCOMMENT_ROOT_CAP", text)
        self.assertIn("PROMOTION_WEEK_TIEBA_SUBCOMMENT_PAGE_CAP", text)

    def test_comment_hierarchy_contract(self):
        text = (ROOT / "scripts" / "patch_tieba_comment_hierarchy.py").read_text(encoding="utf-8")
        self.assertIn("PROMOTION_WEEK_TIEBA_COMMENT_HIERARCHY_V1", text)
        self.assertIn('root_comment_id: str = Field(default="", description="Root comment ID")', text)
        self.assertIn('parent_comment_id=""', text)
        self.assertIn("root_comment_id=parent_comment.root_comment_id or parent_comment.comment_id", text)

    def test_public_region_contract(self):
        text = (ROOT / "scripts" / "patch_tieba_public_regions.py").read_text(encoding="utf-8")
        self.assertIn("PROMOTION_WEEK_TIEBA_PUBLIC_REGION_VERIFY_V1", text)
        self.assertIn('item.get("ip_address")', text)
        self.assertIn('author.get("ip_address")', text)
        self.assertIn('comment_value.get("ip_address")', text)
        self.assertIn("coarse_public_region_only_no_real_ip_no_precise_location", text)

    def test_student_upgrade_deploys_all_tieba_patches(self):
        text = (ROOT / "scripts" / "final_student_update_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("patch_tieba_realtime_resilience.py", text)
        self.assertIn("patch_tieba_comment_hierarchy.py", text)
        self.assertIn("patch_tieba_public_regions.py", text)

    def test_runtime_has_tieba_bounds(self):
        runner = (ROOT / "run_single_platform.py").read_text(encoding="utf-8")
        crawler = (ROOT / "monitor" / "crawler_runner.py").read_text(encoding="utf-8")
        policy = (ROOT / "monitor" / "final_realtime_policy.py").read_text(encoding="utf-8")
        self.assertIn('args.platform == "tieba"', runner)
        self.assertIn('"tieba_realtime_search_timeout_seconds"', runner)
        self.assertIn("TIEBA_REALTIME_SEARCH_TIMEOUT", crawler)
        self.assertIn("PROMOTION_WEEK_TIEBA_REALTIME_DISCOVERY", crawler)
        self.assertIn("PROMOTION_WEEK_TIEBA_REALTIME_DETAIL", policy)


if __name__ == "__main__":
    unittest.main()
