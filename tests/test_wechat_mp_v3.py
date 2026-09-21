from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from wechat.common import CN_TZ
from wechat.mp_records import (assign_identity, canonical_article_url, key_account,
                               merge_records, parse_display_time, validate_record)
from wechat.mp_export import build_tables, export_submission, FIELDS
from wechat.mp_sogou import _parse_card, _extract_records, collect_many
from wechat.mp_pipeline import ingest_result, load_state
from scripts.verify_wechat_mp_final import verify_export

ROOT = Path(__file__).resolve().parents[1]
REF = datetime(2026, 9, 16, 12, 0, tzinfo=CN_TZ)


def row(**changes):
    result = dict(title="2026年民族团结进步宣传周将于9月21日至27日举办", author="人民日报",
                  content="2026年民族团结进步宣传周，活动于9月21日举行。", url="https://weixin.sogou.com/link?url=token&query=A",
                  publish_time="2026-09-16T09:00:00+08:00", collected_at=REF.isoformat(),
                  source_keyword="关键词甲", matched_keywords=["关键词甲"], views=None, likes=None)
    result.update(changes)
    return assign_identity(result)


class Locator:
    def __init__(self, text="", attrs=None, children=None, nodes=None):
        self.text, self.attrs, self.children = text, attrs or {}, children or {}
        self.nodes = [self] if nodes is None else nodes

    @property
    def first(self): return self.nodes[0]
    def count(self): return len(self.nodes)
    def nth(self, i): return self.nodes[i]
    def inner_text(self, **kwargs): return self.text
    def text_content(self, **kwargs): return self.text
    def get_attribute(self, key, **kwargs): return self.attrs.get(key)
    def locator(self, selector): return self.children.get(selector, Locator(nodes=[]))


def card(time_text="3小时前", script=""):
    return Locator(children={
        "h3 a": Locator("2026年民族团结进步宣传周将于9月21日至27日举办", {"href":"/link?token=ABC"}),
        ".txt-info": Locator("将于9月21日至27日举办。"),
        ".s-p .all-time-y2": Locator("人民日报"),
        ".s-p .s2": Locator(time_text),
        ".s-p script": Locator(script) if script else Locator(nodes=[]),
    })


class WechatMPV3Tests(unittest.TestCase):
    def test_real_regression_title_date_cannot_override_footer(self):
        parsed = _parse_card(card(), "关键词甲", REF)
        self.assertEqual(parsed["publish_time"], "2026-09-16T09:00:00+08:00")
        self.assertEqual(parsed["author"], "人民日报")
        self.assertIsNone(parsed["views"])
        self.assertEqual(_parse_card(card(""), "甲", REF)["publish_time"], "")

    def test_timestamp_formats(self):
        expected = {"5分钟前":"2026-09-16T11:55:00+08:00", "3小时前":"2026-09-16T09:00:00+08:00",
                    "昨天":"2026-09-15T00:00:00+08:00", "昨天 09:30":"2026-09-15T09:30:00+08:00",
                    "2026-09-16":"2026-09-16T00:00:00+08:00", "2026年9月16日":"2026-09-16T00:00:00+08:00"}
        for display, value in expected.items():
            with self.subTest(display=display): self.assertEqual(parse_display_time(display, REF), value)
        for bad in ("活动将于9月21日举办 3小时前", "2026-02-30", "9月21日", "", "昨天 99:99"):
            self.assertEqual(parse_display_time(bad, REF), "")

    def test_public_footer_epoch(self):
        epoch = int(REF.timestamp())
        parsed = _parse_card(card("3小时前", f"document.write(timeConvert('{epoch}'))"), "甲", REF)
        self.assertEqual(parsed["publish_time"], REF.isoformat())
        self.assertEqual(parsed["publish_date_exact"], "2026-09-16")

    def test_one_broken_card_does_not_abort_page(self):
        page = Locator(children={"ul.news-list li": Locator(nodes=[card(), card()])})
        errors = []
        with patch("wechat.mp_sogou._parse_card", side_effect=[ValueError("bad"), row()]):
            self.assertEqual(len(_extract_records(page, "甲", 20, errors)), 1)
        self.assertEqual(len(errors), 1)

    def test_cross_keyword_and_round_deduplication(self):
        first = row()
        second = row(url="https://weixin.sogou.com/link?url=other&query=B", source_keyword="关键词乙", matched_keywords=["关键词乙"],
                     publish_time="2026-09-16T09:02:10+08:00", collected_at="2026-09-16T12:02:10+08:00")
        self.assertEqual(first["content_id"], second["content_id"])
        merged = merge_records([first], [second])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["matched_keywords"], ["关键词乙", "关键词甲"])
        self.assertEqual(merged[0]["collected_at"], first["collected_at"])
        self.assertEqual(len(merge_records(merged, [second])), 1)

    def test_canonical_url_ignores_tracking_and_identity_bridges(self):
        url = "https://mp.weixin.qq.com/s?__biz=00123&mid=999999999999999999&idx=1&sn=abc&scene=27&query=x"
        canonical = canonical_article_url(url)
        self.assertNotIn("query", canonical)
        self.assertNotIn("scene", canonical)
        first = row()
        merged = merge_records([first], [row(url=url)])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["canonical_url"], canonical)
        again = merge_records(merged, [row(url=url)])
        self.assertEqual(again[0]["content_id"], first["content_id"])
        self.assertEqual(len(again), 1)
        self.assertEqual(canonical_article_url("https://evil.example/s/a"), "")

    def test_republished_distinct_articles_not_merged(self):
        self.assertEqual(len(merge_records([], [row(url="https://mp.weixin.qq.com/s/a"), row(url="https://mp.weixin.qq.com/s/b")])), 2)
        self.assertEqual(len(merge_records([], [row(publish_date_exact="2026-09-16"), row(publish_date_exact="2026-09-17")])), 2)

    def test_start_time_and_unknown_publication_filter(self):
        self.assertTrue(validate_record(row(publish_time="2026-09-16T00:00:00+08:00"))[0])
        for value in ("2026-09-15T23:59:59+08:00", "", "2026-09-17T00:00:00+08:00"):
            self.assertFalse(validate_record(row(publish_time=value))[0])

    def test_strict_scope(self):
        for text in ("民族团结进步", "首个网络安全宣传周", "2025年民族团结进步宣传周", "2025年首个民族团结进步宣传周", "石榴花开", "民族团结进步倡议", "商业广告2026年民族团结进步宣传周代发软文"):
            self.assertFalse(validate_record(row(title=text, content=text))[0], text)
        self.assertTrue(validate_record(row(title="首个民族团结进步宣传周开幕", content=""))[0])
        self.assertTrue(validate_record(row(title="2026民族团结进步宣传周主场活动", content=""))[0])

    def test_key_account_exact_normalization(self):
        catalog = json.loads((ROOT / "config/key_accounts.wechat_mp.json").read_text(encoding="utf-8"))
        for name in ("人民日报", " 人民日报\u200b ", "南方＋", "石榴云", "云新闻", "广西云"):
            self.assertTrue(key_account(name, catalog)[0], name)
        for name in ("人民日报评论员", "新华社读者", "", "新疆日报/石榴云"):
            self.assertFalse(key_account(name, catalog)[0], name)

    def test_unknown_metrics_are_blank_and_zero_is_preserved(self):
        self.assertEqual([len(fields) for fields in FIELDS], [16, 8, 9, 6, 18])
        tables = build_tables([row()], {}, REF.isoformat())
        self.assertEqual(tables[2][0][3:], [None] * 6)
        self.assertEqual(tables[4][0][11:17], [None] * 6)
        self.assertEqual(tables[1], [])
        self.assertEqual(tables[3], [])
        self.assertEqual(build_tables([row(likes=0)], {}, REF.isoformat())[2][0][4], 0)
        merged = merge_records([row()], [row(likes=0)])
        self.assertEqual(merged[0]["likes"], 0)
        self.assertEqual(merge_records(merged, [row(likes=None)])[0]["likes"], 0)
        for fields, rows in zip(FIELDS, tables):
            for values in rows: self.assertEqual(len(fields), len(values))

    def test_state_merges_keywords_after_restart_and_excludes_old(self):
        with tempfile.TemporaryDirectory() as td, patch("wechat.mp_pipeline.export_state", return_value={}):
            cfg = {"wechat_mp_work_root":td, "monitoring_start_time":"2026-09-16T00:00:00+08:00"}
            ingest_result(cfg, {"status":"SUCCESS", "records":[row(), row(title="old", publish_time="2026-09-15T00:00:00+08:00")]})
            result = ingest_result(cfg, {"status":"SUCCESS", "records":[row(source_keyword="第二词", matched_keywords=["第二词"])]})
            self.assertEqual(result["new_unique"], 0)
            self.assertEqual(result["valid_articles"], 1)
            self.assertEqual(result["filtered_before_start"], 1)
            self.assertEqual(len(load_state(cfg)["records"][0]["matched_keywords"]), 2)

    def test_excel_csv_schema_text_ids_nulls_and_independent_clocks(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = {"wechat_mp_submission_root":td, "monitoring_start_time":"2026-09-16T00:00:00+08:00"}
            result = export_submission([row(author_id="0001234567890123456789")], cfg, {}, REF.isoformat(), {"status":"SUCCESS"}, True)
            directory = Path(result["directory"])
            self.assertTrue(verify_export(directory)["ok"])
            same = export_submission([row()], cfg, {}, (REF+timedelta(minutes=5)).isoformat(), {}, False)
            self.assertFalse(same["updated"])
            export_submission([row(),row(title="第二篇2026年民族团结进步宣传周")], cfg, {}, (REF+timedelta(minutes=15)).isoformat(), {}, False)
            snapshot = json.loads((directory / "export_snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(snapshot["table_counts"], [2, 0, 1, 0, 1])
            self.assertNotEqual(snapshot["content_export_at"], snapshot["metrics_export_at"])
            original_csv = (directory / "01_表1_发布内容.csv").read_bytes()
            with patch("wechat.mp_export.subprocess.run", side_effect=subprocess.CalledProcessError(1, "node")):
                with self.assertRaises(subprocess.CalledProcessError):
                    export_submission([], cfg, {}, (REF+timedelta(hours=1)).isoformat(), {}, True)
            self.assertEqual((directory / "01_表1_发布内容.csv").read_bytes(), original_csv)

    def test_six_real_search_requests_pagination_and_keyword_merge(self):
        from urllib.parse import parse_qs, urlsplit
        with tempfile.TemporaryDirectory() as td:
            cfg = dict(wechat_mp_work_root=td, wechat_mp_search_until_exhausted=True,
                       wechat_mp_max_pages=10, wechat_mp_resolve_article_urls=False)
            browser = MagicMock()
            context = browser.chromium.launch_persistent_context.return_value
            page = MagicMock()
            context.pages = [page]
            def goto(url, **kwargs): page.url = url
            page.goto.side_effect = goto
            def batch(page, keyword, remaining, errors):
                number = parse_qs(urlsplit(page.url).query)["page"][0]
                return [row(title="2026年民族团结进步宣传周" + number, source_keyword=keyword, matched_keywords=[keyword])]
            page.locator.return_value.count.side_effect = lambda: int("page=1" in page.url)
            keywords = ["正式词" + str(i) for i in range(6)]
            with patch("playwright.sync_api.sync_playwright") as pw, patch("wechat.mp_sogou.time.sleep"), \
                 patch("wechat.mp_sogou._wait_for_manual_verify", return_value=True), \
                 patch("wechat.mp_sogou._save_footer_sample"), patch("wechat.mp_sogou._extract_records", side_effect=batch):
                pw.return_value.__enter__.return_value = browser
                result = collect_many(cfg, keywords)
            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(page.goto.call_count, 12)
            self.assertEqual(set(result["per_keyword_pages"].values()), {2})
            self.assertEqual(len(result["records"]), 2)
            self.assertTrue(all(len(r["matched_keywords"]) == 6 for r in result["records"]))

    def test_network_failure_continues_other_keywords(self):
        with tempfile.TemporaryDirectory() as td:
            browser = MagicMock()
            page = MagicMock()
            browser.chromium.launch_persistent_context.return_value.pages = [page]
            page.goto.side_effect = [TimeoutError(), None]
            page.locator.return_value.count.return_value = 0
            with patch("playwright.sync_api.sync_playwright") as pw, patch("wechat.mp_sogou.time.sleep"), \
                 patch("wechat.mp_sogou._wait_for_manual_verify", return_value=True), \
                 patch("wechat.mp_sogou._save_footer_sample"), patch("wechat.mp_sogou._extract_records", return_value=[row()]):
                pw.return_value.__enter__.return_value = browser
                result = collect_many({"wechat_mp_work_root":td, "wechat_mp_resolve_article_urls":False, "wechat_mp_search_until_exhausted":True}, ["甲", "乙"])
            self.assertEqual(result["status"], "PARTIAL")
            self.assertEqual(page.goto.call_count, 2)
            self.assertEqual(result["per_keyword_status"]["甲"], "ERROR")
            self.assertEqual(len(result["records"]), 1)

    def test_official_verification_stops_without_further_search(self):
        with tempfile.TemporaryDirectory() as td:
            browser = MagicMock()
            page = MagicMock()
            browser.chromium.launch_persistent_context.return_value.pages = [page]
            with patch("playwright.sync_api.sync_playwright") as pw, \
                 patch("wechat.mp_sogou._wait_for_manual_verify", return_value=False):
                pw.return_value.__enter__.return_value = browser
                result = collect_many({"wechat_mp_work_root":td}, ["甲", "乙"])
            self.assertEqual(result["status"], "VERIFY_REQUIRED")
            self.assertEqual(page.goto.call_count, 1)

    def test_mp_entry_does_not_import_or_call_classifier(self):
        import sys
        code = """import sys
from unittest.mock import patch
import run_wechat_platform
with patch('wechat.mp_pipeline.run_one_cycle', return_value={'ok': True}) as run:
    assert run_wechat_platform.run_one_cycle({}, 'wechat_mp')['ok']
    run.assert_called_once()
assert 'monitor.ingest' not in sys.modules
assert 'pipeline.classifier' not in sys.modules
assert 'opinion_monitor_v2' not in sys.modules
"""
        subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)


if __name__ == "__main__":
    unittest.main()
