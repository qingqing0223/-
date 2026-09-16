from __future__ import annotations

from pathlib import Path
import time
from urllib.parse import quote, urljoin

from .common import clean_text, make_record, parse_public_time

VERIFY_MARKERS = (
    "验证码用于确认",
    "请输入验证码",
    "antispider",
    "访问过于频繁",
)

RESULT_SELECTORS = (
    "ul.news-list li",
    ".news-list li",
    "li.news-box",
)


def _first_text(node, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        try:
            loc = node.locator(selector)
            if loc.count():
                text = clean_text(loc.first.inner_text(timeout=1200))
                if text:
                    return text
        except Exception:
            continue
    return ""


def _first_attr(node, selectors: tuple[str, ...], attr: str) -> str:
    for selector in selectors:
        try:
            loc = node.locator(selector)
            if loc.count():
                value = loc.first.get_attribute(attr, timeout=1200)
                if value:
                    return clean_text(value)
        except Exception:
            continue
    return ""


def _is_verify(page) -> bool:
    try:
        url = (page.url or "").lower()
        if "antispider" in url:
            return True
        body = clean_text(page.locator("body").inner_text(timeout=1500))
        return any(marker.lower() in body.lower() for marker in VERIFY_MARKERS)
    except Exception:
        return False


def _wait_for_manual_verify(page, seconds: int) -> bool:
    if not _is_verify(page):
        return True
    print("[wechat_mp] 官方验证码/安全验证已出现。请在浏览器中人工完成；程序不会绕过验证码。")
    deadline = time.time() + max(0, seconds)
    while time.time() < deadline:
        time.sleep(2)
        if not _is_verify(page):
            print("[wechat_mp] 人工验证已完成，继续采集。")
            return True
    return False


def _extract_records(page, keyword: str, max_results: int) -> list[dict]:
    nodes = None
    for selector in RESULT_SELECTORS:
        try:
            loc = page.locator(selector)
            if loc.count():
                nodes = loc
                break
        except Exception:
            continue
    if nodes is None:
        return []

    out: list[dict] = []
    seen = set()
    limit = min(nodes.count(), max_results)
    for i in range(limit):
        node = nodes.nth(i)
        try:
            full = clean_text(node.inner_text(timeout=1800))
        except Exception:
            continue
        if len(full) < 6:
            continue

        title = _first_text(node, ("h3 a", "h4 a", "a.tit", "a"))
        href = _first_attr(node, ("h3 a", "h4 a", "a.tit", "a"), "href")
        if href:
            href = urljoin("https://weixin.sogou.com/", href)

        author = _first_text(node, ("a.account", ".s-p a", ".account", "[data-z]"))
        if not title:
            title = clean_text(full.splitlines()[0] if "\n" in full else full[:80])

        key = href or f"{title}|{author}|{full}"
        if key in seen:
            continue
        seen.add(key)

        publish_time = parse_public_time(full)
        out.append(
            make_record(
                platform="wechat_mp",
                keyword=keyword,
                title=title[:200],
                content=full[:4000],
                author=author[:200],
                url=href,
                publish_time=publish_time,
                record_type="post",
                raw_text=full[:4000],
            )
        )
    return out


def collect_many(config: dict, keywords: list[str]) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return {
            "status": "SETUP_REQUIRED",
            "records": [],
            "error": f"playwright_not_available:{type(exc).__name__}:{exc}",
        }

    data_root = Path(config["data_root"])
    profile_dir = data_root.parent / "wechat_browser_data" / "wechat_mp"
    profile_dir.mkdir(parents=True, exist_ok=True)

    max_results = int(config.get("wechat_mp_max_results_per_keyword", 20))
    search_until_exhausted = bool(config.get("wechat_mp_search_until_exhausted", False))
    max_pages = max(1, int(config.get("wechat_mp_max_pages", 1 if not search_until_exhausted else 1000)))
    manual_wait = int(config.get("wechat_manual_verify_wait_seconds", 600))
    delay = max(1.0, float(config.get("wechat_mp_keyword_delay_seconds", 5)))
    records: list[dict] = []
    per_keyword: dict[str, int] = {}
    per_keyword_pages: dict[str, int] = {}

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                str(profile_dir),
                channel="chrome",
                headless=False,
                viewport=None,
                args=["--start-maximized"],
            )
            page = context.pages[0] if context.pages else context.new_page()

            for keyword in keywords:
                keyword_records: list[dict] = []
                keyword_seen = set()
                pages_visited = 0

                for page_number in range(1, max_pages + 1):
                    remaining = max_results - len(keyword_records)
                    if remaining <= 0:
                        break

                    search_url = (
                        "https://weixin.sogou.com/weixin?type=2&query="
                        + quote(keyword)
                        + f"&page={page_number}"
                    )
                    page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(2000)

                    if not _wait_for_manual_verify(page, manual_wait):
                        return {
                            "status": "VERIFY_REQUIRED",
                            "records": records + keyword_records,
                            "per_keyword": per_keyword,
                            "per_keyword_pages": per_keyword_pages,
                            "blocked_keyword": keyword,
                            "search_url": search_url,
                            "error": "manual verification not completed within wait window",
                        }

                    batch = _extract_records(page, keyword, remaining)
                    pages_visited += 1
                    if not batch:
                        break

                    new_on_page = 0
                    for row in batch:
                        key = row.get("content_id") or row.get("url") or row.get("content")
                        if key in keyword_seen:
                            continue
                        keyword_seen.add(key)
                        keyword_records.append(row)
                        new_on_page += 1

                    if new_on_page == 0:
                        break
                    if not search_until_exhausted:
                        break

                    try:
                        has_next = page.locator("#sogou_next").count() > 0
                    except Exception:
                        has_next = False
                    if not has_next:
                        break
                    time.sleep(delay)

                records.extend(keyword_records)
                per_keyword[keyword] = len(keyword_records)
                per_keyword_pages[keyword] = pages_visited
                time.sleep(delay)

            context.close()

        deduped = []
        seen = set()
        for row in records:
            key = row.get("content_id") or row.get("url") or row.get("content")
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)

        return {
            "status": "SUCCESS",
            "records": deduped,
            "per_keyword": per_keyword,
            "per_keyword_pages": per_keyword_pages,
            "visible_results": len(deduped),
            "search_until_exhausted": search_until_exhausted,
        }
    except Exception as exc:
        return {
            "status": "COLLECTOR_ERROR",
            "records": records,
            "per_keyword": per_keyword,
            "per_keyword_pages": per_keyword_pages,
            "error": f"{type(exc).__name__}:{exc}",
        }


def collect(config: dict, keyword: str) -> dict:
    return collect_many(config, [keyword])
