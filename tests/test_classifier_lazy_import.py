from __future__ import annotations

import builtins
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from monitor.ingest import ingest_and_classify
from pipeline.classifier import _load_opinion_monitor_v2, classify_records


class ClassifierLazyImportTests(unittest.TestCase):
    def test_kuaishou_collection_without_classification_never_loads_optional_module(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "search_contents.jsonl"
            raw.write_text(json.dumps({
                "photo_id": "ks-lazy-1",
                "title": "某地民族团结进步宣传周启动仪式",
                "publish_time": "2026-09-21T10:00:00+08:00",
                "source_keyword": "民族团结进步倡议",
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            with patch(
                "pipeline.classifier._load_opinion_monitor_v2",
                side_effect=AssertionError("optional classifier must not be loaded"),
            ):
                result = ingest_and_classify(
                    "ks", [raw], root / "state" / "seen.json",
                    root / "classified" / "classified_results.jsonl",
                    monitoring_start_time="2026-09-21T09:00:00+08:00",
                    monitoring_end_time="2026-09-21T17:00:00+08:00",
                    enable_classification=False,
                )
            self.assertEqual(result["classified_records"], 1)
            self.assertFalse(result["classification_enabled"])

    def test_enabled_classification_reports_missing_optional_module_clearly(self):
        original_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == "opinion_monitor_v2":
                raise ModuleNotFoundError("No module named 'opinion_monitor_v2'", name=name)
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=blocked_import):
            with self.assertRaisesRegex(
                RuntimeError,
                "Opinion classification is enabled.*opinion_monitor_v2.*unavailable",
            ):
                _load_opinion_monitor_v2()

    def test_empty_classification_batch_does_not_require_optional_module(self):
        with patch(
            "pipeline.classifier._load_opinion_monitor_v2",
            side_effect=AssertionError("empty batch must not load classifier"),
        ):
            self.assertEqual(classify_records([]), [])


if __name__ == "__main__":
    unittest.main()
