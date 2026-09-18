from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DouyinStartupResiliencePatchTest(unittest.TestCase):
    def test_patch_script_contract(self):
        text = (ROOT / "scripts" / "patch_douyin_startup_resilience.py").read_text(encoding="utf-8")
        self.assertIn("PROMOTION_WEEK_DY_STARTUP_RESILIENCE_V1", text)
        self.assertIn('wait_until="domcontentloaded"', text)
        self.assertIn('wait_until="commit"', text)
        self.assertIn("for _dy_nav_attempt in range(2):", text)
        self.assertIn("DOUYIN_STARTUP_NETWORK_ERROR", text)

    def test_final_update_applies_patch_for_douyin(self):
        text = (ROOT / "scripts" / "final_student_update_windows.ps1").read_text(encoding="utf-8")
        self.assertIn('if ($Platform -eq "dy")', text)
        self.assertIn("patch_douyin_startup_resilience.py", text)


if __name__ == "__main__":
    unittest.main()
