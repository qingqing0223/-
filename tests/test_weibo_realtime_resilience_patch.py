from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WeiboRealtimeResiliencePatchTest(unittest.TestCase):
    def test_patch_script_contract(self):
        text = (ROOT / "scripts" / "patch_weibo_realtime_resilience.py").read_text(encoding="utf-8")
        self.assertIn("PROMOTION_WEEK_WB_REALTIME_RESILIENCE_V3", text)
        self.assertIn("stop=stop_after_attempt(2)", text)
        self.assertIn("retry_if_not_exception_type(WeiboAccessGuardError)", text)
        self.assertIn("response.status_code in {403, 418, 429, 432}", text)
        self.assertIn("WEIBO_VERIFY_REQUIRED non_json_response", text)
        self.assertIn('wait_until="domcontentloaded", timeout=20000', text)
        self.assertIn('os.environ.get("PROMOTION_WEEK_WB_REALTIME") == "1"', text)
        self.assertIn("WB_DETAIL_VERIFY_STOP", text)
        self.assertIn("except WeiboAccessGuardError:", text)

    def test_runtime_has_weibo_search_bound(self):
        text = (ROOT / "monitor" / "crawler_runner.py").read_text(encoding="utf-8")
        self.assertIn("wb_realtime_search_timeout_seconds", text)
        self.assertIn("WB_REALTIME_SEARCH_TIMEOUT", text)
        self.assertIn("partial_jsonl_preserved=yes", text)

    def test_weibo_search_timeout_with_preserved_data_is_partial_success(self):
        import tempfile
        from monitor.crawler_runner import _classify_state

        with tempfile.TemporaryDirectory() as tmp:
            stdout_log = Path(tmp) / "stdout.log"
            stderr_log = Path(tmp) / "stderr.log"
            stdout_log.write_text("", encoding="utf-8")
            stderr_log.write_text(
                "[monitor] WB_REALTIME_SEARCH_TIMEOUT timeout=100s; partial_jsonl_preserved=yes\n",
                encoding="utf-8",
            )

            state = _classify_state(
                124,
                stdout_log,
                stderr_log,
                content_row_count=59,
                comment_row_count=32,
                comments_enabled=True,
            )

        self.assertEqual(state, "PARTIAL_SUCCESS")
    def test_final_policy_stops_after_verification(self):
        text = (ROOT / "monitor" / "final_realtime_policy.py").read_text(encoding="utf-8")
        self.assertIn("_REALTIME_ACCESS_GUARD_STOP", text)
        self.assertIn('"wb": "WB"', text)
        self.assertIn('"xhs": "XHS"', text)
        self.assertIn('"toutiao": "TOUTIAO"', text)
        self.assertIn("no_more_detail_requests_this_cycle=yes", text)


    def test_weibo_search_timeout_survives_long_later_logs(self):
        import tempfile
        from monitor.crawler_runner import _classify_state

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stdout = root / "stdout.log"
            stderr = root / "stderr.log"

            stdout.write_text(
                "[monitor] WB_REALTIME_SEARCH_TIMEOUT timeout=100s; "
                "partial_jsonl_preserved=yes\n"
                + ("later detail output\n" * 3000),
                encoding="utf-8",
            )

            stderr.write_text(
                ("later CDP noise\n" * 2000)
                + "MediaCrawler ERROR - CDP connection failed: HTTP 502\n",
                encoding="utf-8",
            )

            state = _classify_state(
                124,
                stdout,
                stderr,
                content_row_count=45,
                comment_row_count=1,
                comments_enabled=True,
            )

            self.assertEqual(state, "PARTIAL_SUCCESS")

if __name__ == "__main__":
    unittest.main()
