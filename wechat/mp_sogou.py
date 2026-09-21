from __future__ import annotations

from pathlib import Path
from datetime import datetime
import re
import time
from urllib.parse import urljoin

from .common import CN_TZ, clean_text, make_record, now_cn
from .mp_records import assign_identity, canonical_article_url, merge_records, parse_display_time

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


def _wait_for_manual_verify(page, seconds: int, on_wait=None) -> bool:
    if not _is_verify(page):
        return True
    print("[wechat_mp] 官方验证码/安全验证已出现。请在浏览器中人工完成；程序不会绕过验证码。", flush=True)
    if on_wait:
        on_wait()
    page.bring_to_front()
    deadline = None if seconds < 0 else time.monotonic() + seconds
    if deadline is None:
        print("[wechat_mp] 人工运行模式：持续等待，不设验证超时；Ctrl+C保存进度后退出。", flush=True)
    while deadline is None or time.monotonic() < deadline:
        time.sleep(2)
        if page.is_closed():
            return False
        if not _is_verify(page):
            print("[wechat_mp] 人工验证已完成，从当前进度继续采集。", flush=True)
            return True
    return False


def _resolve_public_url(context, row: dict, manual_wait: int, on_wait=None) -> bool:
    """Click the live public result, letting normal browser navigation run."""
    if row.get("canonical_url") or not row.get("url"):
        return True
    source = context.new_page()
    detail = source
    try:
        search_url = row.get("search_page_url")
        if search_url:
            source.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            source.wait_for_timeout(1500)
            if not _wait_for_manual_verify(source, manual_wait, on_wait):
                return False
            matches = []
            nodes = source.locator(".news-list li")
            for i in range(nodes.count()):
                node = nodes.nth(i)
                candidate = _parse_card(node, "")
                if not candidate or candidate["title"] != row["title"] or candidate["author"] != row["author"]:
                    continue
                if row.get("publish_date_exact") and candidate.get("publish_date_exact") != row["publish_date_exact"]:
                    continue
                matches.append(node.locator("h3 a").first)
            if len(matches) != 1:
                row["url_resolution"] = "public_result_missing_or_ambiguous"
                return True
            link = matches[0]
            # Preserve the current publicly exposed fallback URL if its token changed.
            href = link.get_attribute("href")
            if href:
                row["url"] = urljoin("https://weixin.sogou.com/", href)
            if link.get_attribute("target") == "_blank":
                with source.expect_popup(timeout=10000) as popup:
                    link.click(timeout=10000)
                detail = popup.value
            else:
                link.click(timeout=10000)
        else:
            # Older snapshots may only have a publicly exposed result URL.
            source.goto(row["url"], wait_until="domcontentloaded", timeout=30000)
        detail.wait_for_load_state("domcontentloaded", timeout=15000)
        detail.wait_for_timeout(2000)
        if not _wait_for_manual_verify(detail, manual_wait, on_wait):
            return False
        canonical = canonical_article_url(detail.url)
        if not canonical:
            for selector, attr in (("link[rel='canonical']", "href"), ("meta[property='og:url']", "content")):
                canonical = canonical_article_url(_first_attr(detail, (selector,), attr))
                if canonical:
                    break
        if canonical:
            row["canonical_url"] = canonical
            row["url_resolution"] = "resolved_public_navigation"
        else:
            row["url_resolution"] = "public_destination_not_available"
    except Exception as exc:
        if _is_verify(detail) and not _wait_for_manual_verify(detail, manual_wait, on_wait):
            return False
        row["url_resolution"] = type(exc).__name__
    finally:
        if detail is not source:
            detail.close()
        source.close()
    return True


def _save_footer_sample(page, destination: Path) -> None:
    # Debug only the public source footer. Exclude URLs, credentials and scripts
    # unrelated to the public timestamp; never save the browser's storage state.
    footers = page.locator(".news-list .s-p")
    snippets = []
    for i in range(min(3, footers.count())):
        snippets.append(footers.nth(i).evaluate("""el => {
          const copy = el.cloneNode(true);
          for (const node of [copy, ...copy.querySelectorAll('*')]) {
            for (const attr of [...node.attributes]) {
              if (!['class', 'id'].includes(attr.name)) node.removeAttribute(attr.name);
            }
          }
          return copy.outerHTML;
        }"""))
    if snippets:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text('\n'.join(snippets), encoding="utf-8")


def _parse_card(node, keyword: str, reference: datetime | None = None) -> dict | None:
    reference = reference or now_cn()
    title = _first_text(node, ("h3 a", "h4 a", "a.tit"))
    if not title:
        return None
    href = _first_attr(node, ("h3 a", "h4 a", "a.tit"), "href")
    href = urljoin("https://weixin.sogou.com/", href) if href else ""
    # The account and timestamp are in the source footer, not article prose.
    author = _first_text(node, (".s-p .all-time-y2", ".s-p a.account", ".s-p .account", ".s-p a", "a.account"))
    display_time = _first_text(node, (".s-p .s2", ".s-p .time", ".s-p time", ".s-p [data-time]"))
    published = parse_display_time(display_time, reference)
    time_source = "sogou_display_time" if published else ""
    # Public Sogou cards render their source timestamp using timeConvert(epoch).
    # Only read that script in the source footer; never scan the full card.
    footer_script = node.locator(".s-p script")
    for i in range(footer_script.count()):
        script = footer_script.nth(i).text_content(timeout=1200) or ""
        m = re.search(r"(?:timeConvert|timeConvert2)\(['\"]?(\d{10})['\"]?\)", script)
        if m:
            published = datetime.fromtimestamp(int(m[1]), CN_TZ).isoformat()
            time_source = "sogou_public_footer_epoch"
            break
    content = _first_text(node, (".txt-info", ".txt-box p", ".summary"))
    row = make_record(platform="wechat_mp", keyword=keyword, title=title,
                      content=content, author=author, url=href, publish_time=published)
    row.update(content=content, collected_at=reference.isoformat(timespec="seconds"),
               publish_time_display=display_time, publish_time_source=time_source,
               content_scope="search_result_excerpt", matched_keywords=[keyword],
               author_id=None, account_region=None, original=None,
               views=None, likes=None, comments=None, reposts=None, shares=None, favorites=None)
    if time_source == "sogou_public_footer_epoch" or re.match(r"20\d{2}[-/.年]", display_time):
        row["publish_date_exact"] = published[:10] if published else ""
    return assign_identity(row)


def _extract_records(page, keyword: str, max_results: int, errors: list | None = None) -> list[dict]:
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
    limit = min(nodes.count(), max_results)
    for i in range(limit):
        try:
            row = _parse_card(nodes.nth(i), keyword)
            if row:
                out.append(row)
        except Exception:
            if errors is not None:
                errors.append({"keyword": keyword, "card_index": i, "reason": "card_parse_failed"})
            continue
    return out


def collect_many(config: dict, keywords: list[str]) -> dict:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return {"status": "SETUP_REQUIRED", "records": [], "error": "playwright_not_available"}
    from .mp_search import collect_session
    return collect_session(config, keywords)


def collect(config: dict, keyword: str) -> dict:
    return collect_many(config, [keyword])
