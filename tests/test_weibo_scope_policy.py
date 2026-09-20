from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import monitor.crawler_runner as crawler_runner
from monitor.weibo_scope_policy import (
    MARKER,
    install_weibo_monitoring_scope_queue_policy,
    prune_queue_for_monitoring_scope,
)


class WeiboScopePolicyTest(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def test_prune_removes_only_confirmed_before_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            content_path = Path(tmp) / "weibo" / "jsonl" / "search_contents.jsonl"
            self._write_jsonl(
                content_path,
                [
                    {
                        "note_id": "old",
                        "content": "old post",
                        "create_date_time": "2026-09-15T23:59:59+08:00",
                        "comments_count": "10",
                    },
                    {
                        "note_id": "boundary",
                        "content": "boundary post",
                        "create_date_time": "2026-09-16T00:00:00+08:00",
                        "comments_count": "10",
                    },
                    {
                        "note_id": "new",
                        "content": "new post",
                        "create_date_time": "2026-09-20T12:00:00+08:00",
                        "comments_count": "10",
                    },
                    {
                        "note_id": "unknown",
                        "content": "unknown time post",
                        "comments_count": "10",
                    },
                ],
            )

            queue = {
                "version": 1,
                "items": {
                    "old": {"visible_comment_count": 10},
                    "boundary": {"visible_comment_count": 10},
                    "new": {"visible_comment_count": 10},
                    "unknown": {"visible_comment_count": 10},
                },
            }

            removed = prune_queue_for_monitoring_scope(
                queue,
                [content_path],
                "2026-09-16T00:00:00+08:00",
            )

            self.assertEqual(removed, 1)
            self.assertNotIn("old", queue["items"])
            self.assertIn("boundary", queue["items"])
            self.assertIn("new", queue["items"])
            self.assertIn("unknown", queue["items"])

    def test_installed_policy_does_not_filter_other_platforms(self):
        original_update = crawler_runner._update_queue_from_content

        if hasattr(crawler_runner, MARKER):
            delattr(crawler_runner, MARKER)

        try:
            with tempfile.TemporaryDirectory() as tmp:
                install_weibo_monitoring_scope_queue_policy(
                    tmp,
                    "2026-09-16T00:00:00+08:00",
                )

                xhs_file = Path(tmp) / "xhs_contents.jsonl"
                self._write_jsonl(
                    xhs_file,
                    [
                        {
                            "note_id": "xhs-old",
                            "note_url": "https://example.invalid/xhs-old",
                            "content": "xhs post",
                            "time": "2026-09-15T10:00:00+08:00",
                            "comment_count": 5,
                        }
                    ],
                )

                queue = {"version": 1, "items": {}}
                crawler_runner._update_queue_from_content(
                    "xhs",
                    [xhs_file],
                    queue,
                )

                self.assertIn(
                    "https://example.invalid/xhs-old",
                    queue["items"],
                )
        finally:
            crawler_runner._update_queue_from_content = original_update
            if hasattr(crawler_runner, MARKER):
                delattr(crawler_runner, MARKER)


if __name__ == "__main__":
    unittest.main()