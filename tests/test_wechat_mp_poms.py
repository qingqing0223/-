from contextlib import redirect_stdout, redirect_stderr
import csv
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from tests.test_wechat_mp_daily_batch import today, START, END, KEYWORDS
from wechat.mp_export import FIELDS, FILES, build_tables, csv_value
from wechat.mp_records import assess_record
from wechat.mp_poms_input import convert_batch, check_samples
from scripts.upload_wechat_mp_poms import main

ROOT = Path(__file__).resolve().parents[1]


def source_files(directory, kind="csv"):
    cfg = dict(monitoring_start_time=START, monitoring_end_time=END, keywords=KEYWORDS)
    (directory / "summary.json").write_text(json.dumps(cfg), encoding="utf-8")
    rows = [today(author_id="000123456789012345678901", likes=0),
            today(title="@地方宣传周", content="上下文不足")]
    if kind == "jsonl":
        (directory / "search_contents.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    else:
        catalog = json.loads((ROOT / "config/key_accounts.wechat_mp.json").read_text(encoding="utf-8"))
        tables = build_tables([assess_record(r, START, KEYWORDS, END) for r in rows], catalog, END)
        for fields, name, table in zip(FIELDS, FILES, tables):
            with (directory / name).open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(fields)
                writer.writerows([[csv_value(v) for v in row] for row in table])
    return cfg


class PomsTests(unittest.TestCase):
    def test_csv_and_jsonl_produce_same_arrays_with_null_zero_and_text_ids(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            generated = []
            for kind in ("csv", "jsonl"):
                folder = root / kind
                folder.mkdir()
                source_files(folder, kind)
                result = convert_batch(folder)
                self.assertEqual(result["table_counts"], [2, 0, 1, 0, 1])
                generated.append([json.loads((folder / f"table{i}_batch.json").read_text(encoding="utf-8")) for i in range(1, 6)])
            self.assertEqual(generated[0], generated[1])
            tables = generated[0]
            self.assertEqual(tables[0][0]["publisher_account_id"], "000123456789012345678901")
            self.assertEqual(tables[0][1]["title"], "@地方宣传周")
            self.assertIsNone(tables[0][1]["is_valid_monitoring_data"])
            self.assertIsNone(tables[2][0]["view_or_play_count"])
            self.assertEqual(tables[2][0]["like_count"], 0)

    def test_missing_source_does_not_create_fake_arrays(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            with self.assertRaisesRegex(ValueError, "No CSV/JSONL"):
                convert_batch(folder)
            self.assertEqual(list(folder.iterdir()), [])

    def test_partial_or_out_of_time_csv_is_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            source_files(folder)
            path = folder / FILES[0]
            path.write_text(path.read_text(encoding="utf-8-sig").replace("2026-09-21T10:00:00", "2026-09-21T08:59:59"), encoding="utf-8-sig")
            with self.assertRaisesRegex(ValueError, "out-of-time"):
                convert_batch(folder)
            self.assertFalse((folder / "table1_batch.json").exists())
            (folder / FILES[4]).unlink()
            with self.assertRaisesRegex(ValueError, "Incomplete CSV"):
                convert_batch(folder)

    def test_batch_sample_field_order_is_enforced(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            for path in (ROOT / "batch_test_samples").glob("0[1-5]_batch*.json"):
                shutil.copyfile(path, folder / path.name)
            sample = next(folder.glob("01_*.json"))
            data = json.loads(sample.read_text(encoding="utf-8"))
            data[0] = dict(reversed(list(data[0].items())))
            sample.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "field order"):
                check_samples(folder)

    def test_dry_run_needs_no_credentials_and_never_calls_network(self):
        with tempfile.TemporaryDirectory() as td:
            source_files(Path(td))
            with patch("sys.argv", ["upload", "--batch-dir", td, "--convert", "--dry-run"]), patch.dict("os.environ", {"POMS_URL": "", "POMS_API_KEY": ""}), patch("scripts.upload_wechat_mp_poms.urlopen") as request, redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)
                request.assert_not_called()

    def test_upload_uses_environment_header_ordered_paths_and_stops_on_failure(self):
        with tempfile.TemporaryDirectory() as td:
            source_files(Path(td))
            convert_batch(Path(td))
            sent = []
            def respond(request, **kwargs):
                sent.append(request)
                self.assertEqual(request.get_header("X-api-key"), "local-test-key")
                if len(sent) == 3:
                    raise HTTPError(request.full_url, 422, "validation", {}, None)
                class Response:
                    status = 200
                    def __enter__(self): return self
                    def __exit__(self, *args): pass
                    def read(self): return request.data
                return Response()
            out = io.StringIO()
            with patch("sys.argv", ["upload", "--batch-dir", td]), patch.dict("os.environ", {"POMS_URL": "https://example.invalid", "POMS_API_KEY": "local-test-key"}), patch("scripts.upload_wechat_mp_poms.urlopen", side_effect=respond), redirect_stdout(out), redirect_stderr(out):
                self.assertEqual(main(), 1)
            self.assertEqual(len(sent), 3)
            self.assertTrue(sent[0].full_url.endswith("/published_content_basic_information/batch"))
            self.assertTrue(sent[1].full_url.endswith("/comment_basic_information/batch"))
            self.assertNotIn("local-test-key", out.getvalue())

    def test_windows_wrapper_convert_only_runs_from_another_directory(self):
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if not shell:
            self.skipTest("PowerShell not installed")
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            source_files(folder)
            result = subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts/upload_wechat_poms_windows.ps1"), "-BatchDir", td, "-ConvertOnly"], cwd=td, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            self.assertTrue((folder / "table5_batch.json").exists())
