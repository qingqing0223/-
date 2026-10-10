from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from monitor.weibo_submission_full import TABLE_FILES
from monitor.weibo_submission_schedule import (
    publish_staged_weibo_submission,
)


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class WeiboSubmissionScheduleTests(unittest.TestCase):

    def test_15_minute_and_hourly_publish_cadence_survives_restart(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo_root = root / "repo"
            data_root = root / "data"
            stage_dir = root / "stage"
            repo_root.mkdir()
            data_root.mkdir()
            stage_dir.mkdir()

            cfg = {
                "monitoring_start_time": "2026-09-21T09:00:00+08:00",
                "interval_seconds": 300,
            }

            for key, filename in TABLE_FILES.items():
                _write_rows(
                    stage_dir / filename,
                    [{"table": key, "version": 1}],
                )

            first = publish_staged_weibo_submission(
                stage_dir,
                cfg,
                repo_root,
                data_root,
                "wb01",
                now=datetime.fromisoformat(
                    "2026-09-21T09:05:00+08:00"
                ),
            )

            self.assertTrue(first["table12_published"])
            self.assertTrue(first["table345_published"])

            formal = Path(first["output_dir"])
            self.assertEqual(
                _read_rows(formal / TABLE_FILES["table1"])[0]["version"],
                1,
            )
            self.assertEqual(
                _read_rows(formal / TABLE_FILES["table3"])[0]["version"],
                1,
            )

            # Internal collection can refresh staging at 09:10, but neither
            # formal output group should be sent again within the same slots.
            for key, filename in TABLE_FILES.items():
                _write_rows(
                    stage_dir / filename,
                    [{"table": key, "version": 2}],
                )

            second = publish_staged_weibo_submission(
                stage_dir,
                cfg,
                repo_root,
                data_root,
                "wb01",
                now=datetime.fromisoformat(
                    "2026-09-21T09:10:00+08:00"
                ),
            )

            self.assertFalse(second["table12_published"])
            self.assertFalse(second["table345_published"])
            self.assertEqual(
                _read_rows(formal / TABLE_FILES["table1"])[0]["version"],
                1,
            )
            self.assertEqual(
                _read_rows(formal / TABLE_FILES["table3"])[0]["version"],
                1,
            )

            # 09:15 opens a new quarter-hour slot: Tables 1-2 refresh only.
            third = publish_staged_weibo_submission(
                stage_dir,
                cfg,
                repo_root,
                data_root,
                "wb01",
                now=datetime.fromisoformat(
                    "2026-09-21T09:15:00+08:00"
                ),
            )

            self.assertTrue(third["table12_published"])
            self.assertFalse(third["table345_published"])
            self.assertEqual(
                _read_rows(formal / TABLE_FILES["table1"])[0]["version"],
                2,
            )
            self.assertEqual(
                _read_rows(formal / TABLE_FILES["table3"])[0]["version"],
                1,
            )

            # 10:00 is both a new quarter-hour and a new hour.
            fourth = publish_staged_weibo_submission(
                stage_dir,
                cfg,
                repo_root,
                data_root,
                "wb01",
                now=datetime.fromisoformat(
                    "2026-09-21T10:00:00+08:00"
                ),
            )

            self.assertTrue(fourth["table12_published"])
            self.assertTrue(fourth["table345_published"])
            self.assertEqual(
                _read_rows(formal / TABLE_FILES["table3"])[0]["version"],
                2,
            )

            manifest = json.loads(
                (formal / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["internal_collection_interval_seconds"],
                300,
            )
            self.assertEqual(
                manifest["table12_publish_interval_seconds"],
                900,
            )
            self.assertEqual(
                manifest["table345_publish_interval_seconds"],
                3600,
            )
            self.assertEqual(
                manifest["published_groups"],
                ["table1_table2", "table3_table4_table5"],
            )

            outbox = Path(fourth["publish_outbox"])
            events = _read_rows(outbox)
            self.assertEqual(len(events), 3)
            self.assertEqual(
                events[1]["published_groups"],
                ["table1_table2"],
            )

            # Re-running 10:00 from a restarted process reads persisted state
            # and does not emit duplicate publication events.
            restarted = publish_staged_weibo_submission(
                stage_dir,
                cfg,
                repo_root,
                data_root,
                "wb01",
                now=datetime.fromisoformat(
                    "2026-09-21T10:00:30+08:00"
                ),
            )
            self.assertEqual(restarted["published_groups"], [])
            self.assertEqual(len(_read_rows(outbox)), 3)


if __name__ == "__main__":
    unittest.main()
