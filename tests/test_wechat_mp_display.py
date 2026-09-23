from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import os
import subprocess
import sys

from tests.test_wechat_mp_daily_batch import today, START, END, KEYWORDS
from wechat.mp_records import assess_record
from wechat.mp_display import account_key, empty, normalize_tables
from wechat.mp_export import build_tables, export_submission, FIELDS, WORKBOOK, WORKBOOK_V2
from wechat.mp_poms import poms_rows, validate_schema
from scripts.verify_wechat_mp_final import verify_export


class DisplayTests(unittest.TestCase):
    def test_account_id_is_stable_across_processes(self):
        outputs = []
        for seed in ("1", "987"):
            env = {**os.environ, "PYTHONHASHSEED": seed}
            output = subprocess.check_output([sys.executable, "-c", "from wechat.mp_display import account_key; print(account_key('人民日报'))"],
                                             cwd=Path(__file__).resolve().parents[1], env=env)
            outputs.append(output.strip())
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0].decode(), account_key("人民日报"))

    def test_normalization_is_pure_stable_and_keeps_comments_empty(self):
        records = [assess_record(today(author=" 人民日报 ", content="  "), START, KEYWORDS, END),
                   assess_record(today(title="第二篇2026年民族团结进步宣传周", author="人民日报", likes=7), START, KEYWORDS, END)]
        original = deepcopy(records)
        raw = build_tables(records, {}, END)
        before = deepcopy(raw)
        display = normalize_tables(raw)
        self.assertEqual(records, original)
        self.assertEqual(raw, before)
        self.assertIsNone(records[0]["views"])
        self.assertEqual(display[1], [])
        self.assertEqual(display[3], [])
        self.assertTrue(all(not empty(v) for i in (0, 2, 4) for row in display[i] for v in row))
        key = account_key("人民日报")
        self.assertTrue(key.startswith("local_wxacct_"))
        self.assertEqual(key, account_key(" 人民日报 "))
        self.assertEqual(display[0][0][2], display[0][1][2])
        self.assertEqual(display[0][0][2], display[4][0][0])
        self.assertEqual(display, normalize_tables(display))
        self.assertEqual(display[0][0][8], "公开搜索结果未提供正文摘要")
        self.assertEqual(display[2][1][4], 7)
        # Missing observations must not become trustworthy totals before normalization.
        self.assertIsNone(raw[4][0][12])
        self.assertEqual(display[4][0][12], 0)
        validate_schema([poms_rows(i, table) for i, table in enumerate(display)])

    def test_public_account_id_wins_and_is_shared(self):
        rows = [assess_record(today(author_id="00098765432101234567890"), START, KEYWORDS, END),
                assess_record(today(title="第二篇2026年民族团结进步宣传周", author_id=None), START, KEYWORDS, END)]
        display = normalize_tables(build_tables(rows, {}, END))
        self.assertEqual(display[0][1][2], "00098765432101234567890")
        self.assertEqual(display[4][0][0], display[0][0][2])

    def test_v2_workbook_audit_and_raw_file_are_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td) / "2026-09-21_wechatmp02"
            directory.mkdir()
            record = assess_record(today(), START, KEYWORDS, END)
            original = (json.dumps(record, ensure_ascii=False) + "\n").encode()
            (directory / "search_contents.jsonl").write_bytes(original)
            (directory / WORKBOOK).write_bytes(b"original workbook sentinel")
            cfg = dict(monitoring_start_time=START, monitoring_end_time=END, keywords=KEYWORDS,
                       wechat_mp_submission_date="2026-09-21", wechat_mp_node_id="wechatmp02", wechat_mp_submission_root=td)
            export_submission([record], cfg, {}, END, {}, force=True, preserve_raw=True)
            self.assertEqual((directory / "search_contents.jsonl").read_bytes(), original)
            self.assertEqual((directory / WORKBOOK).read_bytes(), b"original workbook sentinel")
            self.assertTrue((directory / WORKBOOK_V2).exists())
            self.assertTrue(verify_export(directory)["ok"])
            audit = json.loads((directory / "empty_cell_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(len(audit["fields"]), sum(map(len, FIELDS)))
            self.assertTrue(all(item["empty_count"] == 0 for item in audit["fields"]))

    def test_schema_rejects_null_metrics_and_unapproved_enum_changes(self):
        tables = normalize_tables(build_tables([today()], {}, END))
        arrays = [poms_rows(i, table) for i, table in enumerate(tables)]
        arrays[2][0]["like_count"] = None
        with self.assertRaisesRegex(ValueError, "schema"):
            validate_schema(arrays)
