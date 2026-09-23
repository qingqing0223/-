"""Small, independent Google/Bing public discovery; no private APIs or stealth."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlencode, urlsplit

from .common import CN_TZ, clean_text, now_cn, stable_id, write_json
from .mp_records import parse_display_time

VERIFY_MARKERS = ("请输入验证码", "请完成安全验证", "环境异常", "访问过于频繁",
                  "our systems have detected unusual traffic", "verify you are human",
                  "verify that you are human", "one last step", "请验证您是真人")
EXPIRED_MARKERS = ("链接已过期", "该内容已被发布者删除", "此内容因违规无法查看", "内容已删除")


def article_url(value: str) -> str:
    """Accept only an actually observed public article URL, preserving parameters."""
    value = (value or "").strip()
    try:
        p = urlsplit(value)
        if p.scheme not in ("http", "https") or p.hostname != "mp.weixin.qq.com" or p.username or p.password or p.port:
            return ""
        if re.fullmatch(r"/s/[A-Za-z0-9_-]+", p.path) or p.path.rstrip("/") == "/s" and p.query:
            return value
    except ValueError:
        pass
    return ""


def stable_public_url(value: str) -> str:
    value = article_url(value)
    if not value:
        return ""
    p = urlsplit(value)
    q = parse_qs(p.query)
    # Do not turn an expiring address into a permanent URL by dropping its signature.
    if any(k.lower() in {"tempkey", "signature", "timestamp", "expires", "token", "tempkey_expire"} for k in q):
        return ""
    if re.fullmatch(r"/s/[A-Za-z0-9_-]+", p.path) or all(q.get(k) for k in ("__biz", "mid", "idx", "sn")):
        return value
    return ""


def public_navigation_url(value: str) -> str:
    """Sogou is permitted only as the original public /link navigation entry."""
    direct = article_url(value)
    if direct:
        return direct
    try:
        p = urlsplit(value)
        if (p.scheme in ("http", "https") and p.hostname == "weixin.sogou.com"
                and p.path == "/link" and not p.username and not p.password and not p.port):
            return value
    except ValueError:
        pass
    return ""


def build_search_url(source: str, keyword: str) -> str:
    query = 'site:mp.weixin.qq.com/s/ "' + keyword.replace('"', '') + '"'
    if source == "google":
        return "https://www.google.com/search?" + urlencode({"q": query, "hl": "zh-CN", "num": 10})
    if source == "bing":
        return "https://www.bing.com/search?" + urlencode({"q": query, "setlang": "zh-Hans", "count": 10})
    raise ValueError("source must be google or bing")


def records_from_cards(cards: list[dict], source: str, keyword: str, search_url: str, limit: int = 3) -> list[dict]:
    records, seen = [], set()
    observed_at = now_cn().isoformat(timespec="seconds")
    for card in cards:
        url = article_url(card.get("href", ""))
        title = clean_text(card.get("title"))
        if not url or not title or url in seen:
            continue
        seen.add(url)
        records.append({"platform": "wechat_mp", "content_id": "wxmp_discovery_" + stable_id(url),
                        "title": title, "author": "", "publish_time": "", "content": "",
                        "search_snippet": clean_text(card.get("snippet")), "url": url,
                        "canonical_url": "", "canonical_candidate_url": stable_public_url(url),
                        "url_type": "wechat_public_article", "url_resolution": "URL_UNRESOLVED",
                        "discovery_sources": [source], "source_keyword": keyword, "matched_keywords": [keyword],
                        "search_page_url": search_url, "collected_at": observed_at,
                        "discovery_evidence": [{"source": source, "keyword": keyword, "search_url": search_url,
                            "result_url": url, "title": title, "snippet": clean_text(card.get("snippet")), "observed_at": observed_at}],
                        "verified_metadata": False, "review_status": "待核验", "is_valid": False,
                        "invalid_reason": "搜索结果待公开文章页核验标题、帐号和发布时间",
                        "author_id": None, "views": None, "likes": None, "comments": None,
                        "reposts": None, "shares": None, "favorites": None})
        if len(records) >= max(1, min(limit, 3)):
            break
    return records


def _verification(page) -> bool:
    try:
        url = page.url.lower()
        if any(s in url for s in ("/sorry/", "antispider", "/captcha", "/mp/verify")):
            return True
        if page.locator("iframe[src*='recaptcha'], iframe[src*='hcaptcha'], #b_captcha, #captcha").count():
            return True
        body = clean_text(page.locator("body").inner_text(timeout=2000)).lower()
        return any(marker in body for marker in VERIFY_MARKERS)
    except Exception:
        return False


def _publication_time(text: str) -> str:
    parsed = parse_display_time(text)
    if parsed:
        return parsed
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo:
            return dt.astimezone(CN_TZ).isoformat()
    except (ValueError, TypeError):
        pass
    return ""


def metadata_from_dom(dom: dict, final_url: str) -> dict:
    """DOM is restricted to article heading, account, publication area and body."""
    title, author = clean_text(dom.get("title")), clean_text(dom.get("author"))
    published = _publication_time(clean_text(dom.get("publish_time")))
    content = clean_text(dom.get("content"))
    expired = any(m in clean_text(dom.get("body_text")) for m in EXPIRED_MARKERS)
    verified = bool(article_url(final_url) and title and author and published and not expired)
    canonical = "" if expired or not content else stable_public_url(dom.get("canonical_url", "")) or stable_public_url(final_url)
    return {"status": "EXPIRED" if expired else "SUCCESS" if verified else "METADATA_UNVERIFIED",
            "title": title, "author": author, "publish_time": published,
            "publish_time_display": clean_text(dom.get("publish_time")), "publish_time_source": "wechat_public_dom" if published else "",
            "publish_date_exact": published[:10] if published else "", "content": content,
            "content_scope": "public_article_body" if content else "", "verified_metadata": verified,
            "canonical_url": canonical, "final_url": final_url,
            "url_resolution": "PUBLIC_ARTICLE_ACCESSIBLE" if canonical else "URL_UNRESOLVED",
            "canonical_revisit_verified": False, "detail_fetched_at": now_cn().isoformat(timespec="seconds")}


def fetch_public_article(page, url: str) -> dict:
    """One ordinary public navigation; caller owns retry, captcha wait and queue."""
    if not public_navigation_url(url):
        return {"status": "UNSUPPORTED_URL", "verified_metadata": False, "canonical_url": ""}
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1200)
        if _verification(page):
            return {"status": "VERIFY_REQUIRED", "verified_metadata": False, "canonical_url": "", "final_url": page.url}
        if response and response.status >= 400:
            return {"status": "HTTP_ERROR", "http_status": response.status, "verified_metadata": False, "canonical_url": ""}
        dom = page.evaluate("""() => {
          const text = selectors => {for(const s of selectors){const e=document.querySelector(s);if(e && e.innerText.trim())return e.innerText.trim()}return ''};
          const attr = (selectors,a) => {for(const s of selectors){const e=document.querySelector(s);if(e && e.getAttribute(a))return e.getAttribute(a)}return ''};
          return {title:text(['#activity-name','h1.rich_media_title']) || attr(['meta[property="og:title"]'],'content'),
            author:text(['#js_name','#js_profile_qrcode .profile_nickname']),
            publish_time:text(['#publish_time']) || attr(['meta[property="article:published_time"]'],'content'),
            content:text(['#js_content']), canonical_url:attr(['link[rel="canonical"]'],'href') || attr(['meta[property="og:url"]'],'content'),
            body_text:(document.body.innerText || '').slice(0,3000)};
        }""")
        return metadata_from_dom(dom, page.url)
    except Exception as exc:
        if _verification(page):
            return {"status": "VERIFY_REQUIRED", "verified_metadata": False, "canonical_url": ""}
        return {"status": "ERROR", "error": type(exc).__name__, "verified_metadata": False, "canonical_url": ""}


def _cards(page, source: str) -> list[dict]:
    return page.evaluate("""source => {
      const anchors = source==='bing' ? [...document.querySelectorAll('#b_results li.b_algo h2 a')]
        : [...document.querySelectorAll('#search h3')].map(h=>h.closest('a')).filter(Boolean);
      return anchors.map(a=>({href:a.getAttribute('href'),title:a.innerText,
        snippet:(a.closest('li.b_algo') || a.closest('.MjjYud') || a.parentElement).innerText}));
    }""", source)


def search_page_status(cards: list[dict], rows: list[dict], body: str) -> tuple[str, str]:
    if rows:
        return "SUCCESS", ""
    empty_markers = ("did not match any documents", "there are no results for", "no results found",
                     "没有找到与", "未找到相关结果", "没有与此相关的结果", "找不到与")
    if any(marker in clean_text(body).lower() for marker in empty_markers):
        return "NO_RESULTS", "公开页面明确显示无结果"
    if cards:
        return "ERROR", "结果卡片存在，但未取得可接受的微信直达链接（可能为编码跳转或无关结果）"
    return "ERROR", "未识别结果卡片且未发现明确无结果提示，可能为页面变化、访问限制或未完成加载"


def _wait_manual(page, seconds: int, save) -> bool:
    if not _verification(page):
        return True
    save()
    page.bring_to_front()
    print("[wechat_mp] VERIFY_REQUIRED：请在浏览器人工完成验证；不会绕过或重新发起搜索。", flush=True)
    deadline = None if seconds < 0 else time.monotonic() + seconds
    while deadline is None or time.monotonic() < deadline:
        if page.is_closed():
            return False
        page.wait_for_timeout(2000)
        if not _verification(page):
            return True
    return False


def collect_web(config: dict, keywords: list[str], source: str) -> dict:
    """First-page discovery only. Article visits are optional; normally queued."""
    build_search_url(source, "validate")
    from playwright.sync_api import sync_playwright

    work = Path(config.get("wechat_mp_work_root", "data/wechat_mp/public_node"))
    progress = work / "in_progress" / (source + "_progress.json")
    fingerprint = stable_id(json.dumps({"source": source, "keywords": keywords,
        "start": config.get("monitoring_start_time"), "end": config.get("monitoring_end_time")},
        sort_keys=True, ensure_ascii=False))
    try:
        prior = json.loads(progress.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        prior = {}
    # Resume an *incomplete* sweep after a network/captcha interruption. An
    # already completed sweep is fresh on the next normal polling interval.
    resume = prior.get('fingerprint') == fingerprint and not prior.get('complete', False)
    result = prior if resume else {"source": source, "status": "SUCCESS", "records": [], "keyword_stats": {}, "errors": []}
    result['status'] = 'RUNNING'
    result['fingerprint'] = fingerprint
    fresh_observations = 0
    limit = max(1, min(int(config.get("wechat_mp_web_max_results", 3)), 3))
    wait = int(config.get("wechat_mp_manual_verify_wait_seconds", -1))
    def save():
        write_json(progress, result)
    try:
        with sync_playwright() as pw:
            profile = work / ("browser_profile_" + source)
            profile.mkdir(parents=True, exist_ok=True)
            context = pw.chromium.launch_persistent_context(str(profile), headless=False,
                channel=config.get("wechat_mp_browser_channel", "chrome"), viewport={"width": 1280, "height": 900})
            try:
                page = context.new_page()
                for keyword in keywords:
                    if result['keyword_stats'].get(keyword, {}).get('status') in ('SUCCESS', 'NO_RESULTS'):
                        continue
                    stats = {"status": "ERROR", "pages": 0, "raw_hits": 0, "new_records": 0}
                    result["keyword_stats"][keyword] = stats
                    search_url = build_search_url(source, keyword)
                    save()  # Durable cursor before navigation starts.
                    try:
                        response = page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_timeout(1200)
                        if _verification(page):
                            result["status"] = stats["status"] = "VERIFY_REQUIRED"
                            if not _wait_manual(page, wait, save):
                                break
                            result["status"] = "SUCCESS"
                        if response and response.status >= 400:
                            raise RuntimeError("HTTP_" + str(response.status))
                        cards = _cards(page, source)
                        rows = records_from_cards(cards, source, keyword, search_url, limit)
                        status, reason = search_page_status(cards, rows, page.locator("body").inner_text(timeout=3000))
                        stats.update(status=status, pages=1, reason=reason,
                                     raw_hits=sum(bool(article_url(c.get("href", ""))) for c in cards), new_records=len(rows))
                        if status == "ERROR":
                            result["errors"].append({"keyword": keyword, "error": "SearchEvidenceUnavailable", "reason": reason})
                        # Write discovery evidence before any optional article access.
                        result["records"].extend(rows)
                        fresh_observations += len(rows)
                        save()
                        callback = config.get("wechat_mp_on_page")
                        if callback:
                            callback(rows, {"source": source, "keyword": keyword, **stats})
                        if config.get("wechat_mp_web_verify_inline", False):
                            for row in rows:
                                detail = context.new_page()
                                try:
                                    values = fetch_public_article(detail, row["url"])
                                    if values["status"] == "VERIFY_REQUIRED":
                                        result["status"] = stats["status"] = "VERIFY_REQUIRED"
                                        _wait_manual(detail, wait, save)
                                        break  # No automatic revisit after a challenge.
                                    # A failed/empty detail response must not erase the saved card.
                                    for field, value in values.items():
                                        if value not in (None, "") or field not in row:
                                            row[field] = value
                                finally:
                                    detail.close()
                        if result["status"] == "VERIFY_REQUIRED":
                            break
                    except Exception as exc:
                        if _verification(page):
                            result["status"] = stats["status"] = "VERIFY_REQUIRED"
                            _wait_manual(page, wait, save)
                            break
                        stats["status"] = "ERROR"
                        result["errors"].append({"keyword": keyword, "error": type(exc).__name__,
                                                 "reason": "公开搜索访问或页面解析失败"})
                    save()
            finally:
                context.close()
    except Exception as exc:
        result["status"] = "ERROR"
        result["errors"].append({"error": type(exc).__name__, "reason": "公开浏览器启动或运行失败"})
    statuses = [result['keyword_stats'].get(k, {}).get('status') for k in keywords]
    result['complete'] = all(status in ('SUCCESS', 'NO_RESULTS') for status in statuses)
    if result['status'] != 'VERIFY_REQUIRED':
        result['status'] = ('SUCCESS' if result['complete'] and result['records'] else
                            'NO_RESULTS' if result['complete'] else
                            'PARTIAL' if result['records'] else 'ERROR')
    result['fresh_observations'] = fresh_observations
    save()
    return result
