from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bootstrap_bilibili_session_windows.ps1"


class BilibiliBootstrapWindowsTests(unittest.TestCase):
    def test_success_marker_matching_is_whitespace_tolerant(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('$normalizedLogText = ($logText -replace "\\s+", "")', text)
        self.assertIn(
            '$loginVerifiedMarker = $normalizedLogText -match "BILIBILI_LOGIN_VERIFIED"',
            text,
        )
        self.assertIn(
            '$bootstrapOkMarker = $normalizedLogText -match "BILIBILI_SESSION_BOOTSTRAP_OK"',
            text,
        )
        self.assertIn(
            '$verified = $bootstrapOkMarker -or (($rc -eq 0) -and $loginVerifiedMarker)',
            text,
        )

    def test_bootstrap_does_not_depend_on_select_string_line_matching(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn('Select-String "BILIBILI_SESSION_BOOTSTRAP_OK"', text)


if __name__ == "__main__":
    unittest.main()
