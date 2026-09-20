from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse


SEARCH_ENDPOINT = "https://so.toutiao.com/search"
URL_RE = re.compile(r"https?://(?:www\.)?toutiao\.com/(?:(article|video)/(\d+)|a(\d+))")
PROVINCES = (
    "内蒙古","广西","西藏","宁夏","新疆","香港","澳门",
    "北京","天津","上海","重庆","河北","山西","辽宁","吉林","黑龙江",
    "江苏","浙江","安徽","福建","江西","山东","河南","湖北","湖南","广东",
    "海南","四川","贵州","云南","陕西","甘肃","青海","台湾",
)
VERIFY_MARKERS = (
    "安全验证", "验证码", "请完成验证", "访问过于频繁", "操作频繁",
    "请登录后继续", "登录后查看更多", "verify", "captcha",
)


class VerifyRequired(RuntimeError):
    pass


def now_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def coarse_region(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    for prefix in ("IP属地：", "IP属地:", "IP属地", "来自：", "来自:", "来自"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    for province in PROVINCES:
        if province in text:
            return province
    return ""


def to_int(value: Any) -> int:
    text = clean_text(value).replace(",", "").replace("，", "")
    if not text:
        return 0
    try:
        if text.endswith("万"):
            return int(float(text[:-1]) * 10000)
        if text.lower().endswith("w"):
            return int(float(text[:-1]) * 10000)
        if text.lower().endswith("k"):
            return int(float(text[:-1]) * 1000)
        m = re.search(r"\d+(?:\.\d+)?", text)
        return int(float(m.group(0))) if m else 0
    except Exception:
        return 0


def observed_int(value: Any) -> int | None:
    """Return None when the public page did not expose the metric at all."""
    text = clean_text(value)
    return to_int(text) if text else None


def canonical_url(raw: str) -> str:
    raw = unquote(clean_text(raw))
    match = URL_RE.search(raw)
    if not match:
        parsed = urlparse(raw)
        for value in parse_qs(parsed.query).get("url", []):
            match = URL_RE.search(unquote(value))
            if match:
                break
    if not match:
        return ""
    kind = match.group(1) or "article"
    ident = match.group(2) or match.group(3)
    return f"https://www.toutiao.com/{kind}/{ident}/"


def content_id_from_url(url: str) -> str:
    m = URL_RE.search(url)
    return (m.group(2) or m.group(3)) if m else ""


def content_type_from_url(url: str) -> str:
    m = URL_RE.search(url)
    return "video" if m and m.group(1) == "video" else "article"


def append_jsonl(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def search_url(keyword: str) -> str:
    return (
        f"{SEARCH_ENDPOINT}?keyword={quote_plus(keyword)}"
        "&pd=information&source=search_subtab_switch"
        "&enable_druid_v2=1&dvpf=pc&from=news&cur_tab_title=news"
    )


async def body_text(page: Page) -> str:
    try:
        return (await page.locator("body").inner_text(timeout=3000))[:20000]
    except Exception:
        return ""


async def wait_manual_verification(page: Page, seconds: int = 180) -> bool:
    text = (await body_text(page)).lower()
    if not any(marker.lower() in text for marker in VERIFY_MARKERS):
        return True
    print(
        "[toutiao] TOUTIAO_VERIFY_REQUIRED: official login/security verification detected. "
        f"Browser will stay open for up to {seconds}s for manual completion. No bypass is used.",
        flush=True,
    )
    clear_streak = 0
    for remaining in range(seconds, 0, -1):
        if remaining in {seconds, 120, 60, 30, 10}:
            print(f"[toutiao] waiting for manual verification: {remaining}s remaining", flush=True)
        await asyncio.sleep(1)
        current = (await body_text(page)).lower()
        blocked = any(marker.lower() in current for marker in VERIFY_MARKERS)
        if blocked:
            clear_streak = 0
            continue
        clear_streak += 1
        if clear_streak >= 3:
            print("[toutiao] manual verification appears complete; continuing", flush=True)
            return True
    return False


async def settle(page: Page) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    await page.wait_for_timeout(1200)


async def open_checked(page: Page, url: str, timeout_ms: int) -> None:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception as exc:
        print(f"[toutiao] navigation warning: {type(exc).__name__}: {exc}", flush=True)
    await settle(page)
    if not await wait_manual_verification(page):
        raise VerifyRequired("TOUTIAO_VERIFY_REQUIRED manual verification not completed in time")


async def collect_urls(page: Page, keyword: str, limit: int, timeout_ms: int) -> list[str]:
    await open_checked(page, search_url(keyword), timeout_ms)
    urls: list[str] = []
    seen: set[str] = set()
    no_growth = 0
    for _ in range(12):
        hrefs = await page.locator("a[href]").evaluate_all(
            "els => els.map(e => e.href || e.getAttribute('href') || '')"
        )
        before = len(urls)
        for href in hrefs:
            url = canonical_url(str(href))
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
                if len(urls) >= limit:
                    return urls
        if len(urls) == before:
            no_growth += 1
        else:
            no_growth = 0
        if no_growth >= 3:
            break
        await page.mouse.wheel(0, 1800)
        await page.wait_for_timeout(900)
    return urls


ARTICLE_JS = r"""
() => {
  const txt = (selector) => {
    const e = document.querySelector(selector);
    return e ? (e.innerText || e.textContent || '').trim() : '';
  };
  const attr = (selector, name) => {
    const e = document.querySelector(selector);
    return e ? (e.getAttribute(name) || '') : '';
  };
  const first = (selectors) => {
    for (const s of selectors) {
      const v = txt(s);
      if (v) return v;
    }
    return '';
  };
  const meta = (name) =>
    attr(`meta[name="${name}"]`, 'content') ||
    attr(`meta[property="${name}"]`, 'content');

  const body = document.body ? document.body.innerText : '';
  const title = first(['h1','.article-content h1','[class*=title]']) ||
                meta('og:title') || document.title.replace(/_今日头条.*/, '');
  const content = first(['article','.syl-page-article','[class*=article-content]','[class*=articleContent]']) ||
    Array.from(document.querySelectorAll('p')).map(x => (x.innerText || '').trim()).filter(Boolean).join('\n');
  const author = first(['[class*=author] [class*=name]','[class*=author]','[class*=source]']) ||
                 meta('author');
  const publishTime = first(['time','[class*=publish-time]','[class*=time]','[class*=date]']) ||
                      attr('[datetime]','datetime') || meta('article:published_time') ||
                      ((body.match(/20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?/)||[''])[0]);
  const pickCount = (label) => {
    const re = new RegExp(label + '\\s*[:：]?\\s*([0-9,.万wW]+)');
    const m = body.match(re);
    return m ? m[1] : '';
  };
  // Content-level region must come from an explicit author/source-area element.
  // Do not scan the whole page body: comment sections may contain unrelated
  // users' public IP-region labels and must never be attributed to the publisher.
  const regionText = first([
    '[class*=author] [class*=ip]',
    '[class*=author] [class*=region]',
    '[class*=source] [class*=ip]',
    '[class*=source] [class*=region]'
  ]);
  return {
    title, content, author, publishTime,
    likeCount: pickCount('(?:点赞|赞)'),
    commentCount: pickCount('评论'),
    shareCount: pickCount('分享'),
    regionText
  };
}
"""


def _comment_user(node: dict) -> dict:
    for key in ("user", "user_info", "author", "creator"):
        value = node.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _comment_region(node: dict) -> str:
    user = _comment_user(node)
    candidates = [
        node.get("ip_location"), node.get("ip_region"), node.get("ip_label"),
        node.get("province"), node.get("region"), node.get("region_name"),
        node.get("publish_loc"), node.get("user_location"),
        user.get("ip_location"), user.get("ip_region"), user.get("ip_label"),
        user.get("province"), user.get("region"), user.get("location"),
    ]
    for value in candidates:
        region = coarse_region(value)
        if region:
            return region
    return ""


def _comment_id(node: dict) -> str:
    for key in ("comment_id", "id", "cid", "dongtai_id"):
        value = node.get(key)
        if value not in (None, "", 0, "0"):
            return str(value)
    return ""


def _comment_text(node: dict) -> str:
    for key in ("text", "content", "comment_text", "message"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _comment_author(node: dict) -> tuple[str, str]:
    user = _comment_user(node)
    name = user.get("name") or user.get("screen_name") or user.get("nickname") or node.get("user_name") or ""
    uid = user.get("user_id") or user.get("id") or user.get("uid") or node.get("user_id") or ""
    return clean_text(name), clean_text(uid)


def parse_comment_payload(payload: Any, content_id: str) -> list[dict]:
    rows: dict[str, dict] = {}

    def walk(value: Any, parent_id: str = "", root_id: str = "", in_reply: bool = False) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item, parent_id=parent_id, root_id=root_id, in_reply=in_reply)
            return
        if not isinstance(value, dict):
            return

        cid = _comment_id(value)
        text = _comment_text(value)
        current_root = root_id
        if cid and text:
            explicit_parent = clean_text(
                value.get("parent_comment_id")
                or value.get("parent_id")
                or value.get("reply_to_comment_id")
                or value.get("reply_id")
            )
            explicit_root = clean_text(
                value.get("root_comment_id") or value.get("root_id") or value.get("root")
            )
            parent = explicit_parent or (parent_id if in_reply else "")
            current_root = explicit_root or root_id or (parent if parent else cid)
            author, author_id = _comment_author(value)
            row = {
                "platform": "toutiao",
                "content_id": content_id,
                "comment_id": cid,
                "parent_comment_id": parent,
                "root_comment_id": current_root,
                "comment_level": 2 if parent else 1,
                "sub_comment_count": to_int(value.get("reply_count") or value.get("sub_comment_count")),
                "content": text,
                "create_time": value.get("create_time") or value.get("publish_time") or value.get("time"),
                "like_count": value.get("digg_count") or value.get("like_count") or value.get("likes"),
                "nickname": author,
                "user_id": author_id,
                "ip_location": _comment_region(value),
            }
            rows[cid] = row

        for key, child in value.items():
            low = str(key).lower()
            if low in {"reply_list", "replies", "sub_comments", "subcomments", "children"}:
                walk(child, parent_id=cid or parent_id, root_id=current_root or root_id, in_reply=True)
            elif low == "reply_data":
                walk(
                    child,
                    parent_id=cid or parent_id,
                    root_id=current_root or root_id,
                    in_reply=True,
                )
            elif low in {"comments", "comment_list", "data"}:
                walk(child, parent_id=parent_id, root_id=root_id, in_reply=in_reply)

    walk(payload)
    return list(rows.values())


async def extract_dom_comments(page: Page, content_id: str) -> list[dict]:
    script = r"""
    () => {
      const selectors = [
        '[data-comment-id]', '[data-id][class*=comment]', '[class*=comment-item]',
        '[class*=commentItem]', '[class*=reply-item]'
      ];
      const seen = new Set();
      const out = [];
      const pickText = (el, selectors) => {
        for (const selector of selectors) {
          const node = el.querySelector(selector);
          const value = node ? (node.innerText || node.textContent || '').trim() : '';
          if (value) return value;
        }
        return '';
      };
      for (const sel of selectors) {
        for (const el of document.querySelectorAll(sel)) {
          if (seen.has(el)) continue;
          seen.add(el);
          const id = el.getAttribute('data-comment-id') || el.getAttribute('data-id') || '';
          const text = (el.innerText || el.textContent || '').trim();
          if (!id || !text) continue;
          // Region must come from an explicit region/IP child element. Never infer
          // a user's public location from arbitrary province words in comment text.
          const regionText = pickText(el, [
            '[class*=ip-location]', '[class*=ipLocation]', '[class*=ip]',
            '[class*=region]', '[class*=location]'
          ]);
          const authorText = pickText(el, [
            '[class*=user-name]', '[class*=username]', '[class*=author]', '[class*=name]'
          ]);
          const timeText = pickText(el, [
            'time', '[class*=publish-time]', '[class*=time]', '[class*=date]'
          ]);
          out.push({id, text, regionText, authorText, timeText});
        }
      }
      return out;
    }
    """
    try:
        items = await page.evaluate(script)
    except Exception:
        return []
    rows = []
    for item in items or []:
        text = clean_text(item.get("text"))
        cid = clean_text(item.get("id"))
        if not cid or not text:
            continue
        rows.append({
            "platform": "toutiao",
            "content_id": content_id,
            "comment_id": cid,
            "parent_comment_id": "",
            "root_comment_id": cid,
            "comment_level": 1,
            "sub_comment_count": 0,
            "content": text,
            "nickname": clean_text(item.get("authorText")),
            "create_time": clean_text(item.get("timeText")),
            "ip_location": coarse_region(item.get("regionText")),
        })
    return rows


async def fetch_public_comment_api(page: Page, content_id: str, cap: int) -> list[dict]:
    """Try Toutiao's public web comment endpoint using the active browser session.

    This is a best-effort fallback only. It does not generate signatures, bypass
    challenges, or retry through verification. If the endpoint is unavailable,
    the crawler simply falls back to browser-rendered comments.
    """
    if not content_id or cap <= 0:
        return []
    rows: dict[str, dict] = {}
    offset = 0
    page_size = min(20, cap)
    for _ in range(max(1, (cap + page_size - 1) // page_size)):
        url = (
            "https://www.toutiao.com/api/comment/list/"
            f"?group_id={content_id}&item_id={content_id}"
            f"&offset={offset}&count={page_size}"
        )
        try:
            response = await page.context.request.get(
                url,
                headers={
                    "accept": "application/json, text/plain, */*",
                    "referer": canonical_url(page.url) or page.url,
                },
                timeout=12000,
            )
            if response.status in {401, 403, 418, 429}:
                print(
                    f"[toutiao] public comment endpoint unavailable status={response.status}; "
                    "no bypass/retry escalation",
                    flush=True,
                )
                break
            if not response.ok:
                break
            payload = await response.json()
        except Exception as exc:
            print(
                f"[toutiao] public comment endpoint warning: {type(exc).__name__}: {exc}",
                flush=True,
            )
            break

        batch = parse_comment_payload(payload, content_id)
        before = len(rows)
        for row in batch:
            cid = clean_text(row.get("comment_id"))
            if cid:
                rows[cid] = row
                if len(rows) >= cap:
                    return list(rows.values())[:cap]

        data = payload.get("data") if isinstance(payload, dict) else {}
        has_more = bool(data.get("has_more")) if isinstance(data, dict) else False
        if len(rows) == before or not has_more:
            break
        offset += page_size
    return list(rows.values())[:cap]


async def capture_comments(page: Page, content_id: str, cap: int) -> list[dict]:
    captured: dict[str, dict] = {}
    pending: set[asyncio.Task] = set()

    async def handle(response: Response) -> None:
        if "comment" not in response.url.lower():
            return
        try:
            ctype = (response.headers.get("content-type") or "").lower()
            if "json" not in ctype and "javascript" not in ctype:
                return
            payload = await response.json()
        except Exception:
            return
        for row in parse_comment_payload(payload, content_id):
            captured[row["comment_id"]] = row

    def on_response(response: Response) -> None:
        task = asyncio.create_task(handle(response))
        pending.add(task)
        task.add_done_callback(lambda t: pending.discard(t))

    page.on("response", on_response)
    try:
        # The initial detail navigation happens before this helper is called, so
        # some pages have already fired their comment XHRs. Reload once with the
        # response listener attached to capture those public requests.
        try:
            await page.reload(wait_until="domcontentloaded", timeout=15000)
            await settle(page)
        except Exception as exc:
            print(f"[toutiao] comment-capture reload warning: {type(exc).__name__}: {exc}", flush=True)

        for _ in range(10):
            for label in ("展开", "查看全部", "更多回复", "展开更多", "查看更多"):
                try:
                    locator = page.get_by_text(label, exact=False)
                    count = min(await locator.count(), 3)
                    for idx in range(count):
                        try:
                            await locator.nth(idx).click(timeout=500)
                        except Exception:
                            pass
                except Exception:
                    pass
            await page.mouse.wheel(0, 1600)
            await page.wait_for_timeout(900)
            if len(captured) >= cap:
                break
        if pending:
            await asyncio.gather(*list(pending), return_exceptions=True)
        if not captured:
            for row in await fetch_public_comment_api(page, content_id, cap):
                captured[row["comment_id"]] = row
        if not captured:
            for row in await extract_dom_comments(page, content_id):
                captured[row["comment_id"]] = row
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    return list(captured.values())[:cap]


async def fetch_detail(context, url: str, source_keyword: str, timeout_ms: int, get_comments: bool, comment_cap: int):
    page = await context.new_page()
    try:
        await open_checked(page, url, timeout_ms)
        extracted = await page.evaluate(ARTICLE_JS)
        if not isinstance(extracted, dict):
            extracted = {}
        cid = content_id_from_url(page.url or url) or content_id_from_url(url)
        ctype = content_type_from_url(page.url or url)
        content_row = {
            "platform": "toutiao",
            "article_id": cid,
            "content_id": cid,
            "content_type": ctype,
            "title": clean_text(extracted.get("title")),
            "content_text": clean_text(extracted.get("content")),
            "author": clean_text(extracted.get("author")),
            "publish_time": clean_text(extracted.get("publishTime")),
            "like_count": observed_int(extracted.get("likeCount")),
            "comment_count": observed_int(extracted.get("commentCount")),
            "share_count": observed_int(extracted.get("shareCount")),
            "content_url": canonical_url(page.url or url) or url,
            "source_keyword": source_keyword,
            "ip_location": coarse_region(extracted.get("regionText")),
        }
        comments = []
        if get_comments:
            comments = await capture_comments(page, cid, comment_cap)
            if comments and (
                content_row["comment_count"] is None
                or content_row["comment_count"] < len(comments)
            ):
                content_row["comment_count"] = len(comments)
            for row in comments:
                row["source_keyword"] = source_keyword
        return content_row, comments
    finally:
        await page.close()


async def run(args) -> int:
    output_root = Path(args.save_data_path).resolve()
    jsonl_dir = output_root / "toutiao" / "jsonl"
    profile_dir = Path(args.profile_dir).resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    date = now_date()

    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(profile_dir),
            channel="chrome",
            headless=False,
            viewport={"width": 1366, "height": 900},
            locale="zh-CN",
            args=["--disable-notifications"],
        )
        context.set_default_timeout(args.timeout_ms)
        try:
            if args.mode == "search":
                page = context.pages[0] if context.pages else await context.new_page()
                all_content: list[dict] = []
                seen_urls: set[str] = set()
                per_keyword = max(1, args.max_notes // max(1, len(args.keywords)))
                for keyword in args.keywords:
                    urls = await collect_urls(page, keyword, per_keyword, args.timeout_ms)
                    print(f"[toutiao] keyword={keyword!r} discovered={len(urls)}", flush=True)
                    for url in urls:
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                        try:
                            content, _ = await fetch_detail(
                                context, url, keyword, args.timeout_ms, False, args.max_comments
                            )
                            if content.get("content_text") or content.get("title"):
                                all_content.append(content)
                        except VerifyRequired:
                            raise
                        except Exception as exc:
                            print(f"[toutiao] detail warning url={url}: {type(exc).__name__}: {exc}", flush=True)
                        if len(all_content) >= args.max_notes:
                            break
                    if len(all_content) >= args.max_notes:
                        break
                append_jsonl(jsonl_dir / f"search_contents_{date}.jsonl", all_content)
                print(f"[toutiao] search complete content_rows={len(all_content)}", flush=True)
            else:
                urls = [canonical_url(x) or x for x in args.specified_ids if clean_text(x)]
                content_rows: list[dict] = []
                comment_rows: list[dict] = []
                for url in urls:
                    try:
                        content, comments = await fetch_detail(
                            context, url, "", args.timeout_ms, args.get_comment, args.max_comments
                        )
                        content_rows.append(content)
                        comment_rows.extend(comments)
                    except VerifyRequired:
                        raise
                    except Exception as exc:
                        print(f"[toutiao] detail warning url={url}: {type(exc).__name__}: {exc}", flush=True)
                append_jsonl(jsonl_dir / f"detail_contents_{date}.jsonl", content_rows)
                append_jsonl(jsonl_dir / f"detail_comments_{date}.jsonl", comment_rows)
                print(
                    f"[toutiao] detail complete content_rows={len(content_rows)} "
                    f"comment_rows={len(comment_rows)}",
                    flush=True,
                )
        finally:
            await context.close()
    return 0


def parse_args():
    ap = argparse.ArgumentParser(description="Bounded Toutiao public web crawler for the promotion-week monitor.")
    ap.add_argument("--mode", choices=("search", "detail"), required=True)
    ap.add_argument("--keywords", default="")
    ap.add_argument("--specified-id", default="")
    ap.add_argument("--save-data-path", required=True)
    ap.add_argument("--profile-dir", required=True)
    ap.add_argument("--max-notes", type=int, default=20)
    ap.add_argument("--max-comments", type=int, default=100)
    ap.add_argument("--get-comment", choices=("yes", "no"), default="yes")
    ap.add_argument("--timeout-ms", type=int, default=25000)
    ns = ap.parse_args()
    ns.keywords = [x.strip() for x in ns.keywords.split(",") if x.strip()]
    ns.specified_ids = [x.strip() for x in ns.specified_id.split(",") if x.strip()]
    return ns


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(run(args))
    except VerifyRequired as exc:
        print(f"[toutiao] TOUTIAO_VERIFY_REQUIRED: {exc}", file=sys.stderr, flush=True)
        return 23
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"[toutiao] crawler failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
