from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DouyinCommentRequestProfilePatchTest(unittest.TestCase):
    def test_patch_script_contract(self):
        text = (ROOT / "scripts" / "patch_douyin_comment_request_profile.py").read_text(encoding="utf-8")
        self.assertIn("PROMOTION_WEEK_DY_COMMENT_REQUEST_PROFILE_V2", text)
        self.assertIn('"browser_platform": "Win32"', text)
        self.assertIn('"version_code": "170400"', text)
        self.assertIn('params.setdefault("insert_ids", "")', text)
        self.assertIn('self.cookie_dict.get("msToken")', text)
        self.assertIn('params["verifyFp"]', text)
        self.assertIn('"count": 50', text)
        self.assertIn("return await self.get(uri, params, headers=headers)", text)

    def test_acceptance_applies_request_profile_patch(self):
        text = (ROOT / "scripts" / "test_douyin_realtime_5min_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("patch_douyin_comment_request_profile.py", text)

    def test_final_student_update_applies_request_profile_patch(self):
        text = (ROOT / "scripts" / "final_student_update_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("patch_douyin_comment_request_profile.py", text)


if __name__ == "__main__":
    unittest.main()
