from wechat.mp_web_discovery import (
    article_url, build_search_url, metadata_from_dom, records_from_cards, stable_public_url,
)


def test_only_observed_direct_article_links_are_accepted():
    cards = [
        {"href": "https://mp.weixin.qq.com/s/real-article", "title": "真实标题", "snippet": "摘要"},
        {"href": "https://www.bing.com/ck/a?u=a1encoded", "title": "编码跳转"},
        {"href": "https://mp.weixin.qq.com.evil.example/s/abc", "title": "伪域名"},
        {"href": "javascript:alert(1)", "title": "脚本"},
        {"href": "https://mp.weixin.qq.com/s/real-article", "title": "重复"},
    ]
    rows = records_from_cards(cards, "bing", "正式关键词", "https://www.bing.com/search?q=test")
    assert len(rows) == 1
    assert rows[0]["matched_keywords"] == ["正式关键词"]
    assert rows[0]["discovery_sources"] == ["bing"]
    assert rows[0]["publish_time"] == ""
    assert rows[0]["author"] == ""
    assert rows[0]["views"] is None
    assert not rows[0]["is_valid"]
    assert rows[0]["canonical_url"] == ""


def test_signed_address_is_not_upgraded_by_parameter_removal():
    url = "https://mp.weixin.qq.com/s?__biz=abc&mid=123&idx=1&sn=real&tempkey=temporary"
    assert article_url(url) == url
    assert stable_public_url(url) == ""
    assert stable_public_url("https://mp.weixin.qq.com/s?__biz=abc&mid=123&idx=1") == ""
    stable = "https://mp.weixin.qq.com/s?__biz=abc&mid=123&idx=1&sn=real"
    assert stable_public_url(stable) == stable


def test_metadata_comes_from_public_article_fields_not_body_dates():
    dom = {"title": "2026年民族团结进步宣传周", "author": "公开帐号", "publish_time": "2026年9月23日 10:15",
           "content": "正文活动将在9月27日结束", "body_text": "完整页面"}
    row = metadata_from_dom(dom, "https://mp.weixin.qq.com/s/real-article")
    assert row["verified_metadata"]
    assert row["publish_time"] == "2026-09-23T10:15:00+08:00"
    assert row["canonical_url"] == "https://mp.weixin.qq.com/s/real-article"
    assert row["canonical_revisit_verified"] is False
    dom["publish_time"] = ""
    row = metadata_from_dom(dom, "https://mp.weixin.qq.com/s/real-article")
    assert row["publish_time"] == ""
    assert not row["verified_metadata"]


def test_expired_mp_domain_is_not_a_resolved_article():
    row = metadata_from_dom({"title": "旧标题", "author": "帐号", "publish_time": "2026-09-23 12:00",
        "content": "链接已过期", "body_text": "链接已过期"}, "https://mp.weixin.qq.com/s/expired")
    assert row["status"] == "EXPIRED"
    assert not row["verified_metadata"]
    assert row["canonical_url"] == ""


def test_readable_temporary_article_can_supply_body_without_stable_url():
    row = metadata_from_dom({"title": "真实标题", "author": "帐号", "publish_time": "2026-09-23 12:00",
                            "content": "真实正文"}, "https://mp.weixin.qq.com/s?signature=temporary")
    assert row["verified_metadata"]
    assert row["content"] == "真实正文"
    assert row["canonical_url"] == ""
    assert row["url_resolution"] == "URL_UNRESOLVED"


def test_public_query_and_three_result_limit():
    from urllib.parse import parse_qs, urlsplit
    for source in ("google", "bing"):
        query = parse_qs(urlsplit(build_search_url(source, "民族团结进步宣传周")).query)["q"][0]
        assert query == 'site:mp.weixin.qq.com/s/ "民族团结进步宣传周"'
    cards = [{"title": str(i), "href": f"https://mp.weixin.qq.com/s/article{i}"} for i in range(8)]
    assert len(records_from_cards(cards, "google", "关键词", "search", limit=100)) == 3


def test_fetch_failure_preserves_queue_retry_status():
    from wechat.mp_web_discovery import fetch_public_article
    class FailedPage:
        url = "about:blank"
        def goto(self, *args, **kwargs):
            raise TimeoutError()
        def locator(self, *args):
            raise RuntimeError()
    assert fetch_public_article(FailedPage(), "https://mp.weixin.qq.com/s/test")["status"] == "ERROR"
    assert fetch_public_article(FailedPage(), "https://example.com")["status"] == "UNSUPPORTED_URL"


def test_captcha_stops_article_extraction():
    from wechat.mp_web_discovery import fetch_public_article
    class ChallengePage:
        url = "https://mp.weixin.qq.com/mp/verify"
        def goto(self, *args, **kwargs):
            return None
        def wait_for_timeout(self, *args):
            pass
        def evaluate(self, *args):
            raise AssertionError("Must not extract protected page")
    assert fetch_public_article(ChallengePage(), "https://mp.weixin.qq.com/s/test")["status"] == "VERIFY_REQUIRED"


def test_sogou_entry_allows_only_normal_public_link_navigation():
    from wechat.mp_web_discovery import public_navigation_url
    url = "https://weixin.sogou.com/link?url=real_observed_value"
    assert public_navigation_url(url) == url
    assert public_navigation_url("https://weixin.sogou.com/api/private") == ""
    assert public_navigation_url("https://weixin.sogou.com.evil/link?url=abc") == ""
    row = metadata_from_dom({"title": "标题", "author": "作者", "publish_time": "2026-09-23 12:00"}, url)
    assert not row["verified_metadata"]


def test_search_empty_dom_is_not_reported_as_no_results():
    from wechat.mp_web_discovery import search_page_status
    assert search_page_status([], [], "Loading or changed layout")[0] == "ERROR"
    assert search_page_status([], [], "Your search did not match any documents")[0] == "NO_RESULTS"
    assert search_page_status([{"href": "https://bing.com/ck/encoded"}], [], "results")[0] == "ERROR"
    assert search_page_status([], [{"title": "result"}], "results")[0] == "SUCCESS"


def test_discovery_callback_runs_after_checkpoint_before_next_keyword(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    import playwright.sync_api
    from wechat import mp_web_discovery as web
    calls = []
    class Page:
        url = "https://www.google.com/search"
        def goto(self, url, **kwargs):
            calls.append("navigate")
            return SimpleNamespace(status=200)
        def wait_for_timeout(self, *args):
            pass
        def locator(self, *args):
            return SimpleNamespace(inner_text=lambda **kwargs: "public results")
    class Context:
        def new_page(self):
            return Page()
        def close(self):
            pass
    class Driver:
        chromium = SimpleNamespace(launch_persistent_context=lambda *args, **kwargs: Context())
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", Driver)
    monkeypatch.setattr(web, "_verification", lambda page: False)
    monkeypatch.setattr(web, "_cards", lambda page, source: [{"href": "https://mp.weixin.qq.com/s/real", "title": "title"}])
    def callback(rows, progress):
        saved = json.loads((tmp_path / "in_progress/google_progress.json").read_text(encoding="utf-8"))
        assert saved["records"]
        assert rows[0]["source_keyword"] == progress["keyword"]
        calls.append("callback")
    result = web.collect_web({"wechat_mp_work_root": str(tmp_path), "wechat_mp_on_page": callback}, ["one", "two"], "google")
    assert result["status"] == "SUCCESS"
    assert calls == ["navigate", "callback", "navigate", "callback"]


def test_public_search_checkpoint_retries_only_failed_keyword(tmp_path, monkeypatch):
    """After a simulated network failure, successful previous cards are retained."""
    import json
    from types import SimpleNamespace
    from urllib.parse import parse_qs, urlsplit
    import playwright.sync_api
    from wechat import mp_web_discovery as web

    attempts = []
    fail_second = [True]
    class Page:
        url = 'about:blank'
        def goto(self, url, **kwargs):
            self.url = url
            term = parse_qs(urlsplit(url).query)['q'][0]
            if 'second' in term and fail_second[0]:
                attempts.append('fail-second')
                raise TimeoutError('simulated')
            attempts.append('second' if 'second' in term else 'first')
            return SimpleNamespace(status=200)
        def wait_for_timeout(self, *args):
            pass
        def locator(self, *args):
            return SimpleNamespace(inner_text=lambda **kwargs: 'ordinary public search results')
    class Context:
        def new_page(self):
            return Page()
        def close(self):
            pass
    class Driver:
        chromium = SimpleNamespace(launch_persistent_context=lambda *args, **kwargs: Context())
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(playwright.sync_api, 'sync_playwright', Driver)
    monkeypatch.setattr(web, '_verification', lambda page: False)
    def cards(page, source):
        keyword = 'second' if 'second' in parse_qs(urlsplit(page.url).query)['q'][0] else 'first'
        return [{'href': 'https://mp.weixin.qq.com/s/' + keyword, 'title': 'Observed ' + keyword}]
    monkeypatch.setattr(web, '_cards', cards)
    cfg = {'wechat_mp_work_root': str(tmp_path), 'wechat_mp_manual_verify_wait_seconds': 0}
    first = web.collect_web(cfg, ['first', 'second'], 'bing')
    assert first['status'] == 'PARTIAL'
    assert len(first['records']) == 1
    persisted = json.loads((tmp_path / 'in_progress/bing_progress.json').read_text('utf-8'))
    assert persisted['records'][0]['title'] == 'Observed first'
    assert persisted['keyword_stats']['first']['status'] == 'SUCCESS'
    fail_second[0] = False
    second = web.collect_web(cfg, ['first', 'second'], 'bing')
    assert attempts == ['first', 'fail-second', 'second']
    assert second['status'] == 'SUCCESS'
    assert second['complete'] is True
    assert len(second['records']) == 2
    assert second['fresh_observations'] == 1
