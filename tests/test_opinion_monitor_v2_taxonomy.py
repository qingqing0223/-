from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "v2"))

from dashboard_adapter.suqi_pusher import _canonical_status_type as adapter_canonical
from dashboard_adapter.suqi_pusher import to_suqi_record
from monitor.result_summary import _attitude_bucket, _canonical_status_type, _tri_class_bucket
from pipeline.classifier import _tri_class_from_decision
from opinion_monitor_v2.schema import ClassificationError, TYPE_BY_STATUS, validate_output


class OpinionMonitorV22TaxonomyTests(unittest.TestCase):
    def test_l1_has_exactly_three_statuses(self):
        self.assertEqual(set(TYPE_BY_STATUS), {"normal", "attention", "problematic"})

    def test_attention_has_three_l2_types(self):
        self.assertEqual(
            TYPE_BY_STATUS["attention"],
            frozenset({"neutral", "information_gap", "consultation"}),
        )
        result = validate_output({"status": "attention", "type": "neutral"})
        self.assertEqual(result.to_dict(), {"status": "attention", "type": "neutral"})

    def test_retired_neutral_l1_and_null_l2_are_rejected(self):
        for value in (
            {"status": "neutral", "type": None},
            {"status": "attention", "type": None},
        ):
            with self.assertRaises(ClassificationError):
                validate_output(value)

    def test_legacy_pair_is_canonicalized_only_for_downstream_compatibility(self):
        self.assertEqual(_canonical_status_type("neutral", None), ("attention", "neutral"))
        self.assertEqual(adapter_canonical("neutral", None), ("attention", "neutral"))

    def test_reporting_buckets_use_attention_subtype(self):
        self.assertEqual(_attitude_bucket("attention", "neutral"), "neutral")
        self.assertEqual(_attitude_bucket("attention", "information_gap"), "attention")
        self.assertEqual(_attitude_bucket("attention", "consultation"), "attention")

    def test_three_class_review_mapping(self):
        cases = {
            "normal": "support",
            "attention": "neutral",
            "problematic": "non_support",
        }
        for status, expected in cases.items():
            self.assertEqual(
                _tri_class_from_decision({"status": status, "type": "support"}),
                expected,
            )
            self.assertEqual(_tri_class_bucket(status), expected)

    def test_dashboard_receives_canonical_labels_for_legacy_rows(self):
        record = to_suqi_record({
            "platform": "dy",
            "sample_id": "legacy-1",
            "content": "客观转述",
            "status": "neutral",
            "type": None,
        })
        self.assertEqual(record["attitude"], "中性信息")
        self.assertEqual(record["issue_category"], "")
        self.assertIn("v2_status=attention", record["notes"])
        self.assertIn("v2_type=neutral", record["notes"])


if __name__ == "__main__":
    unittest.main()
