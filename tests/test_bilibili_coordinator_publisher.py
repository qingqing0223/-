from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BilibiliCoordinatorPublisherContractTests(unittest.TestCase):
    def test_powershell_script_uses_real_newlines_and_correct_target(self):
        path = ROOT / "scripts" / "publish_bili_coordinator_once_windows.ps1"
        text = path.read_text(encoding="utf-8")
        self.assertNotIn(r"\n", text)
        self.assertTrue(text.startswith("param(\n"))
        self.assertIn('[string]$NodeId = "bili-coordinator"', text)
        self.assertIn("--platform bili", text)
        self.assertIn("--node-id $NodeId", text)
        self.assertIn("--push", text)
        self.assertIn("results/YYYY-MM-DD/nodes/bili/$NodeId.json", text)


if __name__ == "__main__":
    unittest.main()
