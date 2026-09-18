from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DouyinRealtimeCadenceAndRegionBackfillTest(unittest.TestCase):
    def test_student_soft_empty_cooldown_is_five_minutes(self):
        text = (ROOT / "scripts" / "start_student_platform_windows.ps1").read_text(encoding="utf-8")
        self.assertIn('Set-ConfigProperty $cfgObj "soft_empty_cooldown_seconds" 300', text)
        self.assertNotIn('Set-ConfigProperty $cfgObj "soft_empty_cooldown_seconds" 1800', text)

    def test_orchestrator_soft_empty_is_start_to_start(self):
        text = (ROOT / "monitor" / "orchestrator.py").read_text(encoding="utf-8")
        self.assertIn("soft_empty_cooldown - elapsed", text)
        self.assertIn('cfg.get("soft_empty_cooldown_seconds", interval)', text)

    def test_publisher_contains_node_build_metadata(self):
        text = (ROOT / "scripts" / "publish_node_result_to_github.py").read_text(encoding="utf-8")
        self.assertIn('"node_build": _node_build_metadata(cfg)', text)
        self.assertIn("PROMOTION_WEEK_DY_COMMENT_REQUEST_PROFILE_V2", text)

    def test_region_backfill_enriches_existing_only(self):
        text = (ROOT / "scripts" / "backfill_douyin_comment_regions.py").read_text(encoding="utf-8")
        self.assertIn("_merge_regions_into_existing", text)
        self.assertIn("Only existing classified Douyin comment rows are enriched", text)
        self.assertNotIn("append_jsonl(", text)

    def test_windows_wrapper_applies_request_profile_v2(self):
        text = (ROOT / "scripts" / "backfill_douyin_comment_regions_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("patch_douyin_comment_request_profile.py", text)
        self.assertIn("backfill_douyin_comment_regions.py", text)


if __name__ == "__main__":
    unittest.main()
