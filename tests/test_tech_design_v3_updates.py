from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from monitor.account_info import TABLE5_FIELDS, build_table5_account_rows, write_table5_account_snapshots
from monitor.result_summary import build_summary, write_summary


ROOT = Path(__file__).resolve().parents[1]


class TechDesignV3UpdateTests(unittest.TestCase):
    def test_v3_key_account_catalog_contains_four_required_categories(self):
        catalog = json.loads((ROOT / "config" / "key_accounts.v3.catalog.json").read_text(encoding="utf-8"))
        cats = {row["account_type"]: row["accounts"] for row in catalog["categories"]}
        self.assertEqual(set(cats), {"中央媒体", "统战系统媒体", "卫视媒体", "地方媒体"})
        self.assertIn("人民日报", cats["中央媒体"])
        self.assertIn("国家民委", cats["统战系统媒体"])
        self.assertIn("新疆卫视", cats["卫视媒体"])
        self.assertIn("北京日报", cats["地方媒体"])

    def test_test_stage_interval_stays_five_minutes_until_capability_acceptance(self):
        cfg = json.loads((ROOT / "config" / "key_accounts.example.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["monitoring_start_time"], "2026-09-16T00:00:00+08:00")
        self.assertEqual(cfg["interval_seconds"], 300)
        self.assertEqual(cfg["key_account_catalog"], "config/key_accounts.v3.catalog.json")

    def test_toutiao_key_account_wiring_exists(self):
        orchestrator = (ROOT / "run_key_accounts.py").read_text(encoding="utf-8")
        creator_runner = (ROOT / "monitor" / "creator_runner.py").read_text(encoding="utf-8")
        adapter = (ROOT / "scripts" / "toutiao_crawler.py").read_text(encoding="utf-8")
        starter = (ROOT / "scripts" / "start_key_accounts_windows.ps1").read_text(encoding="utf-8")
        self.assertIn('"toutiao": "今日头条"', orchestrator)
        self.assertIn('platform == "toutiao"', creator_runner)
        self.assertIn('"creator"', adapter)
        self.assertIn("PROFILE_JS", adapter)
        self.assertIn('"toutiao"', starter)

    def test_table5_snapshot_contains_required_fields_and_public_metrics(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            classified = root / "classified.jsonl"
            classified.write_text(
                json.dumps({
                    "dedupe_key": "toutiao:1",
                    "sample_id": "1",
                    "platform": "toutiao",
                    "record_type": "post",
                    "author": "人民日报",
                    "author_id": "token-rmrb",
                    "likes": 10,
                    "comments": 3,
                    "shares": 2,
                    "views": 100,
                    "favorites": 1,
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            raw = root / "account_info_2026-09-20.jsonl"
            raw.write_text(
                json.dumps({
                    "creator_id": "token-rmrb",
                    "account_id": "uid-rmrb",
                    "account_name": "人民日报",
                    "profile_url": "https://www.toutiao.com/c/user/token/token-rmrb/",
                    "followers": 1000,
                    "following": 5,
                    "region": "北京",
                    "organization": "人民日报社",
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            rows = build_table5_account_rows(
                "toutiao",
                [{
                    "platform": "toutiao",
                    "name": "人民日报",
                    "creator_id": "token-rmrb",
                    "account_type": "中央媒体",
                    "organization": "人民日报社",
                    "is_key_account": True,
                }],
                classified,
                [raw],
            )
            self.assertEqual(len(rows), 1)
            row = rows[0]
            for field in TABLE5_FIELDS:
                self.assertIn(field, row)
            self.assertEqual(row["account_type"], "中央媒体")
            self.assertTrue(row["is_key_account"])
            self.assertEqual(row["related_post_count"], 1)
            self.assertEqual(row["total_interactions"], 16)
            written = write_table5_account_snapshots(root, rows)
            self.assertTrue(Path(written["latest"]).exists())
            self.assertTrue(Path(written["daily"]).exists())

    def test_summary_exposes_and_persists_hourly_overall_trend(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            data_root = base / "data_toutiao"
            classified_dir = data_root / "classified"
            classified_dir.mkdir(parents=True)
            rows = [
                {
                    "dedupe_key": "toutiao:p1",
                    "sample_id": "p1",
                    "platform": "toutiao",
                    "record_type": "post",
                    "author": "人民日报",
                    "author_id": "a1",
                    "publish_time": "2026-09-20T10:00:00+08:00",
                    "first_seen_time": "2026-09-20T10:05:00+08:00",
                    "likes": 10,
                    "comments": 2,
                    "shares": 3,
                    "views": 100,
                    "favorites": 1,
                    "status": "attention",
                    "type": "neutral",
                },
                {
                    "dedupe_key": "toutiao:c1",
                    "sample_id": "c1",
                    "platform": "toutiao",
                    "record_type": "comment",
                    "comment_id": "c1",
                    "content_id": "p1",
                    "author": "用户甲",
                    "author_id": "u1",
                    "publish_time": "2026-09-20T10:10:00+08:00",
                    "first_seen_time": "2026-09-20T10:11:00+08:00",
                    "status": "attention",
                    "type": "neutral",
                },
            ]
            with (classified_dir / "classified_results.jsonl").open("w", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")

            summary = build_summary([data_root], monitoring_start_time="2026-09-16T00:00:00+08:00")
            trend = summary["overall_trend_current"]
            self.assertEqual(trend["information_total"], 2)
            self.assertEqual(trend["published_content_count"], 1)
            self.assertEqual(trend["comment_reply_count"], 1)
            self.assertEqual(trend["spreading_account_count"], 2)
            self.assertEqual(trend["interaction_total"], 16)

            repo_root = base / "repo"
            out = write_summary(repo_root, summary, result_date="2026-09-20")
            trend_path = Path(out["overall_hourly_trend"])
            self.assertTrue(trend_path.exists())
            persisted = [json.loads(line) for line in trend_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(persisted), 1)
            self.assertEqual(persisted[0]["information_total"], 2)


if __name__ == "__main__":
    unittest.main()
