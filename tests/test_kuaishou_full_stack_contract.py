from pathlib import Path
import unittest

from pipeline.normalizer import normalize_record


class KuaishouFullStackContractTests(unittest.TestCase):
    def test_missing_engagement_is_not_fabricated_as_zero(self):
        row = normalize_record({"platform": "ks", "video_id": "v1", "title": "x"})
        self.assertIsNone(row["likes"])
        self.assertIsNone(row["comments"])

    def test_real_zero_is_preserved(self):
        row = normalize_record({
            "platform": "ks", "video_id": "v1", "title": "x",
            "realLikeCount": 0, "commentCount": 0,
        })
        self.assertEqual(row["likes"], 0)
        self.assertEqual(row["comments"], 0)

    def test_public_profile_counts_are_retained(self):
        row = normalize_record({
            "platform": "ks", "video_id": "v1", "title": "x",
            "follower_count": "11.9万", "following_count": "53",
        })
        self.assertEqual(row["follower_count"], 119000)
        self.assertEqual(row["following_count"], 53)

    def test_cdp_helper_has_no_hardcoded_drive_and_disables_connect_existing(self):
        text = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "enable_mediacrawler_cdp.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("-MediaCrawlerRoot", text)
        self.assertIn("'CDP_CONNECT_EXISTING' = 'False'", text)
        self.assertNotIn('$target = "E:\\MediaCrawler_clean', text)

    def test_student_launcher_applies_complete_kuaishou_stack(self):
        text = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "start_student_platform_windows.ps1"
        ).read_text(encoding="utf-8")
        for script in (
            "enable_mediacrawler_cdp.ps1",
            "patch_kuaishou_startup_resilience.py",
            "patch_kuaishou_login_resilience.py",
            "patch_kuaishou_comment_regions.py",
            "patch_kuaishou_comment_hierarchy.py",
            "patch_kuaishou_engagement_fields.py",
            "patch_kuaishou_creator_trial_safety.py",
            "patch_kuaishou_public_metrics.py",
        ):
            self.assertIn(script, text)


if __name__ == "__main__":
    unittest.main()
