from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from tests.test_wechat_mp_v3 import row
from wechat.mp_records import assess_record, candidate_counts
from wechat.mp_export import export_submission
from wechat.mp_poms import POMS_FIELDS, poms_rows
from wechat.mp_pipeline import ingest_result, validate_config
from wechat.mp_sogou import collect_many, _resolve_public_url, _wait_for_manual_verify
from scripts.verify_wechat_mp_final import verify_export
from scripts.upload_wechat_mp_poms import prepare_uploads

ROOT = Path(__file__).resolve().parents[1]
START = "2026-09-21T09:00:00+08:00"
END = "2026-09-21T17:00:00+08:00"
KEYWORDS = ["民族团结进步倡议", "2026年民族宣传周主场活动", "民族团结进步宣传周主题宣传片", "促进民族团结进步，奋进伟大复兴征程"]


def today(**changes):
    defaults = dict(publish_time="2026-09-21T10:00:00+08:00", collected_at="2026-09-21T18:00:00+08:00",
                    source_keyword=KEYWORDS[0], matched_keywords=[KEYWORDS[0]])
    defaults.update(changes)
    return row(**defaults)


def fake_browser(stack, batch, verify=True, next_page=None, body=""):
    browser, page = MagicMock(), MagicMock()
    browser.chromium.launch_persistent_context.return_value.pages = [page]
    def goto(url, **kwargs): page.url = url
    page.goto.side_effect = goto
    def locator(selector):
        loc = MagicMock()
        loc.count.return_value = 1 if selector == "#sogou_next" and next_page and next_page(page.url) else 0
        loc.inner_text.return_value = body
        return loc
    page.locator.side_effect = locator
    pw = stack.enter_context(patch("playwright.sync_api.sync_playwright"))
    pw.return_value.__enter__.return_value = browser
    stack.enter_context(patch("wechat.mp_sogou._extract_records", side_effect=batch))
    waiter = stack.enter_context(patch("wechat.mp_sogou._wait_for_manual_verify"))
    if isinstance(verify, list): waiter.side_effect = verify
    else: waiter.return_value = verify
    stack.enter_context(patch("wechat.mp_sogou._save_footer_sample"))
    stack.enter_context(patch("wechat.mp_search.time.sleep"))
    return page


class DailyBatchTests(unittest.TestCase):
    def test_today_config_four_keywords_isolated_paths(self):
        cfg = json.loads((ROOT / "config/monitoring.wechat.2026-09-21.json").read_text(encoding="utf-8"))
        validate_config(cfg)
        self.assertEqual(cfg["keywords"], KEYWORDS)
        self.assertEqual(cfg["monitoring_start_time"], START)
        self.assertEqual(cfg["monitoring_end_time"], END)
        self.assertEqual(cfg["wechat_mp_node_id"], "wechatmp02")
        self.assertEqual(cfg["wechat_mp_submission_date"], "2026-09-21")
        self.assertIn("2026-09-21_wechatmp02", cfg["wechat_mp_work_root"])
        self.assertEqual(cfg["wechat_mp_manual_verify_wait_seconds"], -1)

    def test_time_window_includes_exact_boundaries_and_excludes_history(self):
        for timestamp in (START, END, "2026-09-21T12:00:00+08:00"):
            self.assertTrue(assess_record(today(publish_time=timestamp), START, KEYWORDS, END)["candidate_eligible"])
        for timestamp in ("2026-09-20T23:59:59+08:00", "2026-09-21T08:59:59+08:00", "2026-09-21T17:00:01+08:00", ""):
            self.assertFalse(assess_record(today(publish_time=timestamp), START, KEYWORDS, END)["candidate_eligible"])

    def test_pending_and_invalid_remain_candidates_but_unsearched_does_not(self):
        records = [today(), today(title="地方宣传周", content="上下文不足"),
                   today(title="商业广告", content="有偿代写")]
        assessed = [assess_record(r, START, KEYWORDS, END) for r in records]
        self.assertEqual([r["review_status"] for r in assessed], ["是", "待核验", "否"])
        self.assertEqual(candidate_counts(assessed), dict(total_candidates=3, valid_articles=1, invalid_articles=1, pending_review_articles=1))
        unrelated = today(source_keyword="非正式词", matched_keywords=["非正式词"])
        self.assertFalse(assess_record(unrelated, START, KEYWORDS, END)["candidate_eligible"])

    def test_full_artifact_contract_and_no_yesterday_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            yesterday = Path(td) / "2026-09-20_wechatmp01"
            yesterday.mkdir()
            (yesterday / "keep.txt").write_text("yesterday", encoding="utf-8")
            cfg = dict(monitoring_start_time=START, monitoring_end_time=END, keywords=KEYWORDS,
                       wechat_mp_submission_date="2026-09-21", wechat_mp_node_id="wechatmp02", wechat_mp_submission_root=td)
            records = [today(author_id="0001234567890123456789", likes=0),
                       today(title="地方宣传周", content="上下文不足"),
                       today(title="商业广告", content="有偿代写"),
                       today(title="历史", publish_time="2026-09-21T08:59:59+08:00"),
                       today(title="超出时段", publish_time="2026-09-21T17:00:01+08:00")]
            result = export_submission(records, cfg, {}, "2026-09-22T10:00:00+08:00", {}, True)
            out = Path(result["directory"])
            self.assertEqual(out.name, "2026-09-21_wechatmp02")
            self.assertTrue(verify_export(out)["ok"])
            summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["table_counts"], [3, 0, 1, 0, 1])
            self.assertEqual([summary[k] for k in ("total_candidates", "valid_articles", "invalid_articles", "pending_review_articles")], [3, 1, 1, 1])
            arrays = [json.loads((out / f"table{i}_batch.json").read_text(encoding="utf-8")) for i in range(1, 6)]
            self.assertEqual(arrays[1], [])
            self.assertEqual(arrays[3], [])
            self.assertEqual(arrays[0][0]["publisher_account_id"], "0001234567890123456789")
            self.assertEqual(arrays[2][0]["view_or_play_count"], 0)
            self.assertEqual(arrays[2][0]["like_count"], 0)
            self.assertEqual([r["is_valid_monitoring_data"] for r in arrays[0]], [True, False, False])
            self.assertTrue(arrays[0][1]["invalid_reason"])
            self.assertEqual(arrays[0][0]["matched_keywords"], [KEYWORDS[0]])
            self.assertEqual((yesterday / "keep.txt").read_text(encoding="utf-8"), "yesterday")
            endpoints = {f"table{i}": f"https://example.invalid/table{i}" for i in range(1, 6)}
            requests = prepare_uploads(out, {"endpoints": endpoints})
            self.assertEqual(json.loads(requests[0][2])[0]["publisher_account_id"], "0001234567890123456789")
            self.assertEqual(json.loads(requests[1][2]), [])
            with patch.dict("os.environ", {"POMS_URL": "https://example.invalid"}):
                requests = prepare_uploads(out, {})
                self.assertEqual(requests[0][1], "https://example.invalid/api/v1/tables/published_content_basic_information/batch")
            with patch.dict("os.environ", {"POMS_URL": ""}), self.assertRaises(ValueError):
                prepare_uploads(out, {})

    def test_poms_matches_supplied_sample_field_order(self):
        samples = sorted((ROOT / "batch_test_samples").glob("0[1-5]_batch*.json"))
        if len(samples) != 5:
            self.skipTest("User-supplied POMS samples are not installed")
        for fields, sample in zip(POMS_FIELDS, samples):
            records = json.loads(sample.read_text(encoding="utf-8-sig"))
            self.assertEqual(fields, list(records[0]))

    def test_resume_skips_completed_keywords_and_preserves_multikeyword_hits(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = dict(wechat_mp_work_root=td, wechat_mp_search_until_exhausted=True, wechat_mp_resolve_article_urls=False)
            def batch(page, keyword, *_): return [row(source_keyword=keyword, matched_keywords=[keyword])]
            with ExitStack() as stack:
                page = fake_browser(stack, batch, verify=[True, False])
                first = collect_many(cfg, ["甲", "乙"])
            self.assertEqual(first["keyword_coverage"], {"甲": "SUCCESS", "乙": "VERIFY_REQUIRED"})
            with ExitStack() as stack:
                page = fake_browser(stack, batch)
                second = collect_many(cfg, ["甲", "乙"])
                self.assertEqual(page.goto.call_count, 1)
            self.assertTrue(second["search_acceptance_complete"])
            self.assertEqual(second["keyword_coverage"], {"甲": "SUCCESS", "乙": "SUCCESS"})
            self.assertEqual(len(second["records"]), 1)
            self.assertEqual(set(second["records"][0]["matched_keywords"]), {"甲", "乙"})
            self.assertEqual(second["keyword_stats"]["甲"]["new_unique"], 1)
            self.assertEqual(second["keyword_stats"]["乙"]["new_unique"], 0)

    def test_resume_current_page_after_verification(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = dict(wechat_mp_work_root=td, wechat_mp_search_until_exhausted=True, wechat_mp_resolve_article_urls=False)
            def batch(page, keyword, *_):
                number = parse_qs(urlsplit(page.url).query)["page"][0]
                return [row(title="文章" + number, source_keyword=keyword, matched_keywords=[keyword])]
            with ExitStack() as stack:
                fake_browser(stack, batch, verify=[True, False], next_page=lambda url: "page=1" in url)
                first = collect_many(cfg, ["甲"])
            self.assertEqual(first["keyword_stats"]["甲"]["next_page"], 2)
            with ExitStack() as stack:
                page = fake_browser(stack, batch)
                second = collect_many(cfg, ["甲"])
                self.assertIn("page=2", page.goto.call_args.args[0])
                self.assertEqual(page.goto.call_count, 1)
            self.assertEqual(len(second["records"]), 2)
            self.assertEqual(second["keyword_stats"]["甲"]["pages"], 2)
            self.assertEqual(second["keyword_stats"]["甲"]["raw_hits"], 2)

    def test_no_results_has_explicit_status_for_all_four_keywords(self):
        with tempfile.TemporaryDirectory() as td, ExitStack() as stack:
            page = fake_browser(stack, lambda *_: [], body="没有找到相关结果")
            result = collect_many(dict(wechat_mp_work_root=td, wechat_mp_resolve_article_urls=False), KEYWORDS)
            self.assertEqual(page.goto.call_count, 4)
            self.assertTrue(result["search_acceptance_complete"])
            self.assertEqual(set(result["keyword_coverage"].values()), {"NO_RESULTS"})

    def test_manual_verification_wait_continues_without_automated_action(self):
        page = MagicMock()
        page.is_closed.return_value = False
        callback = MagicMock()
        with patch("wechat.mp_sogou._is_verify", side_effect=[True, True, False]), patch("wechat.mp_sogou.time.sleep"):
            self.assertTrue(_wait_for_manual_verify(page, -1, callback))
        callback.assert_called_once()
        page.goto.assert_not_called()
        page.evaluate.assert_not_called()

    def test_canonical_is_obtained_by_normal_click_and_id_stays_stable(self):
        context, source, detail, link = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        context.new_page.return_value = source
        source.locator.return_value.count.return_value = 1
        source.locator.return_value.nth.return_value.locator.return_value.first = link
        link.get_attribute.side_effect = lambda k: {"href": "/link?token=fresh", "target": "_blank"}.get(k)
        source.expect_popup.return_value.__enter__.return_value.value = detail
        detail.url = "https://mp.weixin.qq.com/s/publicArticle?scene=27"
        record = today(search_page_url="https://weixin.sogou.com/weixin?type=2&query=example&page=1")
        identifier = record["content_id"]
        with patch("wechat.mp_sogou._parse_card", return_value=dict(record)), patch("wechat.mp_sogou._wait_for_manual_verify", return_value=True):
            self.assertTrue(_resolve_public_url(context, record, -1))
        link.click.assert_called_once()
        detail.goto.assert_not_called()
        self.assertEqual(record["canonical_url"], "https://mp.weixin.qq.com/s/publicArticle")
        self.assertEqual(record["content_id"], identifier)

    def test_unavailable_canonical_is_not_collector_failure(self):
        context, source = MagicMock(), MagicMock()
        context.new_page.return_value = source
        source.locator.return_value.count.return_value = 0
        record = today(search_page_url="https://weixin.sogou.com/weixin?type=2&query=example")
        original_url = record["url"]
        with patch("wechat.mp_sogou._wait_for_manual_verify", return_value=True):
            self.assertTrue(_resolve_public_url(context, record, -1))
        self.assertEqual(record["url"], original_url)
        self.assertFalse(record["canonical_url"])


if __name__ == "__main__":
    unittest.main()
