from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.archive_raw_runs_to_git import (
    _write_non_support_review_feed,
    _write_non_support_review_sheet,
)


class NonSupportReviewQueueTests(unittest.TestCase):
    def test_private_review_queue_and_manual_confirmation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data_root = root / "data"
            archive = root / "private"
            classified = data_root / "classified" / "classified_results.jsonl"
            classified.parent.mkdir(parents=True)
            archive.mkdir()

            rows = [
                {
                    "dedupe_key": "bili:1",
                    "platform": "bili",
                    "record_type": "comment",
                    "status": "problematic",
                    "type": "criticism",
                    "tri_class": "non_support",
                    "classification_state": "ok",
                    "classification_method": "v2",
                    "publish_time": "2026-09-18T10:00:00+08:00",
                    "first_seen_time": "2026-09-18T10:01:00+08:00",
                    "language": "汉语",
                    "ip_location": "广东",
                    "source_keyword": "测试关键词",
                    "author": "测***户",
                    "content": "需要人工复核的公开评论",
                    "context": "母帖上下文",
                    "url": "https://example.com/public-post",
                    "comment_level": 1,
                },
                {
                    "dedupe_key": "bili:2",
                    "platform": "bili",
                    "record_type": "comment",
                    "status": "normal",
                    "type": "support",
                    "tri_class": "support",
                    "publish_time": "2026-09-18T10:00:00+08:00",
                    "content": "支持内容",
                },
            ]
            classified.write_text(
                "\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n",
                encoding="utf-8",
            )

            queue = _write_non_support_review_feed(
                data_root,
                archive,
                "bili01",
                "bili",
                "2026-09-16T00:00:00+08:00",
            )
            self.assertIsNotNone(queue)
            payload = json.loads(queue.read_text(encoding="utf-8"))
            self.assertEqual(payload["pending_non_support_count"], 1)
            self.assertEqual(payload["records"][0]["model_tri_class"], "non_support")
            self.assertEqual(payload["records"][0]["content"], "需要人工复核的公开评论")

            sheet, confirmed = _write_non_support_review_sheet(
                queue, archive, "bili01", "bili"
            )
            self.assertTrue(sheet.exists())
            self.assertTrue(confirmed.exists())

            with sheet.open("r", encoding="utf-8-sig", newline="") as fh:
                review_rows = list(csv.DictReader(fh))
            self.assertEqual(len(review_rows), 1)
            review_rows[0]["manual_label"] = "non_support"
            review_rows[0]["manual_note"] = "人工确认"
            review_rows[0]["reviewer"] = "student-a"
            review_rows[0]["reviewed_at"] = "2026-09-18T20:00:00+08:00"

            with sheet.open("w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=review_rows[0].keys())
                writer.writeheader()
                writer.writerows(review_rows)

            _, confirmed = _write_non_support_review_sheet(
                queue, archive, "bili01", "bili"
            )
            confirmed_payload = json.loads(confirmed.read_text(encoding="utf-8"))
            self.assertEqual(confirmed_payload["confirmed_non_support_count"], 1)
            item = confirmed_payload["records"][0]
            self.assertEqual(item["manual_label"], "non_support")
            self.assertEqual(item["manual_note"], "人工确认")
            self.assertEqual(item["content"], "需要人工复核的公开评论")


if __name__ == "__main__":
    unittest.main()
