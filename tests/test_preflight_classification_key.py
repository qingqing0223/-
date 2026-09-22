from __future__ import annotations

import unittest

from scripts.preflight import _dashscope_api_key_check


class PreflightClassificationKeyTests(unittest.TestCase):
    def test_kuaishou_skip_classification_without_key_is_non_blocking(self):
        result = _dashscope_api_key_check(
            {"kuaishou_skip_opinion_classification": True},
            environ={},
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["required"])
        self.assertEqual(result["status"], "skipped")
        self.assertIn("Tables 1-5", result["detail"])

    def test_enabled_classification_without_key_is_required_failure(self):
        result = _dashscope_api_key_check(
            {"kuaishou_skip_opinion_classification": False},
            environ={},
        )
        self.assertFalse(result["ok"])
        self.assertTrue(result["required"])
        self.assertEqual(result["status"], "missing")


if __name__ == "__main__":
    unittest.main()
