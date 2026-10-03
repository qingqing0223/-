from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_bilibili_acceptance_config.py"


class BuildBilibiliAcceptanceConfigTests(unittest.TestCase):
    def test_script_runs_directly_and_loads_project_policy(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            base = td / "monitoring.local.json"
            out = td / "monitoring.bili-acceptance.json"
            base.write_text(
                json.dumps({
                    "data_root": str(td / "data"),
                    "media_crawler_root": str(td / "MediaCrawler"),
                    "classifier_concurrency": 4,
                    "platforms": [
                        {"code": "bili", "name": "哔哩哔哩", "enabled": True},
                        {"code": "dy", "name": "抖音", "enabled": True},
                    ],
                }, ensure_ascii=False),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--base", str(base),
                    "--output", str(out),
                ],
                cwd=str(ROOT),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            cfg = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(cfg["monitoring_start_time"], "2026-09-16T00:00:00+08:00")
            self.assertEqual(len(cfg["keywords"]), 11)
            self.assertTrue(cfg["campaign_search_expand"])
            self.assertTrue(cfg["campaign_strict_admission"])
            self.assertTrue(next(x for x in cfg["platforms"] if x["code"] == "bili")["enabled"])
            self.assertFalse(next(x for x in cfg["platforms"] if x["code"] == "dy")["enabled"])


if __name__ == "__main__":
    unittest.main()
