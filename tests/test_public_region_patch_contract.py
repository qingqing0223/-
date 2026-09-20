from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PublicRegionPatchContractTest(unittest.TestCase):
    def test_helper_normalizes_public_labels_and_rejects_real_ip(self):
        path = ROOT / "scripts" / "public_region_helper_template.py"
        spec = importlib.util.spec_from_file_location("public_region_helper_template", path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        self.assertEqual(module.coarse_public_region("IP属地：山东"), "山东")
        self.assertEqual(module.coarse_public_region("发布于 北京"), "北京")
        self.assertEqual(module.coarse_public_region("所在地: 内蒙古自治区"), "内蒙古")
        self.assertEqual(module.coarse_public_region("1.2.3.4"), "")
        self.assertEqual(module.coarse_public_region("2001:db8::1"), "")
        self.assertEqual(module.coarse_public_region("未知"), "")
        self.assertEqual(module.coarse_public_region("CN"), "")
        self.assertEqual(module.coarse_public_region("China"), "")
        self.assertEqual(module.first_coarse_public_region("CN", "IP属地：四川"), "四川")

    def test_patch_is_v4_and_covers_all_platforms(self):
        text = (ROOT / "scripts" / "patch_mediacrawler_public_regions.py").read_text(encoding="utf-8")
        self.assertIn("PROMOTION_WEEK_PUBLIC_REGION_PATCH_V4", text)
        for fn in (
            "patch_douyin", "patch_xhs", "patch_weibo", "patch_kuaishou",
            "patch_bilibili", "patch_zhihu",
        ):
            self.assertIn(f"def {fn}", text)
        self.assertIn('note_item.get("ipLocation")', text)
        self.assertIn('comment_item.get("ipRegion")', text)

        toutiao = (ROOT / "scripts" / "toutiao_crawler.py").read_text(encoding="utf-8")
        self.assertIn("TOUTIAO_VERIFY_REQUIRED", toutiao)
        self.assertIn("capture_comments", toutiao)
        self.assertIn("parent_comment_id", toutiao)
        self.assertIn("ip_location", toutiao)

    def test_final_student_update_applies_generic_and_kuaishou_specific_patch(self):
        text = (ROOT / "scripts" / "final_student_update_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("patch_mediacrawler_public_regions.py", text)
        self.assertIn("verify_mediacrawler_public_regions.py", text)
        self.assertIn("patch_kuaishou_comment_regions.py", text)
        self.assertIn("patch_kuaishou_comment_hierarchy.py", text)

    def test_acceptance_inspector_exists(self):
        self.assertTrue((ROOT / "scripts" / "inspect_public_region_acceptance.py").exists())
        self.assertTrue((ROOT / "scripts" / "check_public_region_acceptance_windows.ps1").exists())

    def test_public_region_inspector_bootstraps_repo_root(self):
        text = (ROOT / "scripts" / "inspect_public_region_acceptance.py").read_text(encoding="utf-8")
        self.assertIn("ROOT = Path(__file__).resolve().parents[1]", text)
        self.assertIn("sys.path.insert(0, str(ROOT))", text)

    def test_final_student_start_uses_named_splatting(self):
        text = (ROOT / "scripts" / "final_student_update_windows.ps1").read_text(encoding="utf-8")
        self.assertIn('$startArgs = @{', text)
        self.assertIn('& .\\scripts\\start_student_platform_windows.ps1 @startArgs', text)
        self.assertNotIn('$args = @(', text)

    def test_result_sync_rewinds_failed_local_result_commit(self):
        text = (ROOT / "scripts" / "publish_node_result_to_github.py").read_text(encoding="utf-8")
        self.assertIn('stage": "git_precommit_pull"', text)
        self.assertIn("rollback_local_result_commit", text)
        self.assertIn('_run_git(["reset", "--mixed", base_head])', text)
        self.assertIn('stage": "git_push_auth"', text)
        self.assertIn('stage": "git_postcommit_rebase"', text)


if __name__ == "__main__":
    unittest.main()
