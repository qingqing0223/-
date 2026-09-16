# -*- coding: utf-8 -*-
"""省市政务/媒体网站通用采集模板（v1：标题级）

适用于四类网站：
  1) 省政府门户 / 省民宗委（政务公告、要闻）
  2) 省级主流媒体 / 地方媒体（新闻列表）
  3) 网信办 / 举报平台
  4) 自治州 / 自治县政府门户

采集策略：
  - 抓取站点首页/栏目页 HTML；
  - 解析全部 <a> 链接与标题（含容器内发布时间，尽力而为）；
  - 用 SEARCH_KEYWORDS 过滤“民族相关”新闻标题；
  - 输出 24 字段原始记录，交给 collect.py 归一化。

注意：
  - 这是“标题级”采集，正文、评论、态度暂不抓取，后续再加详情页模板；
  - 部分政府站为 GBK 编码，已做多编码回退；
  - 403/412 反爬站点已在 site_sources.json 中标记 enabled=false。
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse

import config
from collectors.base import BaseCollector

try:
    from lxml import html as lxml_html

    HAVE_LXML = True
except Exception:
    HAVE_LXML = False

UA_MAIN = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
UA_ALT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 Edg/120.0"
)

EXCLUDE_PATH = re.compile(
    r"/(search|login|register|about|contact|sitemap|rss|feed|help|privacy|"
    r"user|member|account|javascript|tag|tags)/",
    re.I,
)
DATE_RE = re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})")
META_CHARSET_RE = re.compile(r'<meta[^>]+charset=["\']?\s*([\w-]+)', re.I)


def _decode(raw, headers=None):
    """按 HTTP 头 / meta charset / 常见编码顺序解码。"""
    cs = ""
    if headers and headers.get("Content-Type"):
        m = re.search(r"charset=([\w-]+)", str(headers.get("Content-Type")), re.I)
        if m:
            cs = m.group(1).strip().strip('"').strip("'")
    if not cs:
        m = META_CHARSET_RE.search(raw[:4096].decode("ascii", "ignore"))
        if m:
            cs = m.group(1)
    candidates = ([cs] if cs else []) + ["utf-8", "gb18030", "gbk", "latin-1"]
    for enc in candidates:
        if not enc:
            continue
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", "ignore")


class SiteNewsCollector(BaseCollector):
    name = "site_news"
    label = "省市政务/媒体网站"
    enabled = True
    interval = 1800
    note = "通用 HTML 标题级采集：省政府/民宗委/省级媒体/自治州县政府；正文与态度待扩展"

    def __init__(self):
        self.enabled = config.SITE_NEWS_ENABLED
        self.interval = config.SITE_NEWS_INTERVAL

    def _headers(self, alt=False):
        return {
            "User-Agent": UA_ALT if alt else UA_MAIN,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    def _fetch(self, url, timeout=20):
        last = None
        for attempt in range(2):
            req = urllib.request.Request(url, headers=self._headers(alt=(attempt == 1)))
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read(2_000_000)
                    headers = dict(resp.headers.items())
                    return _decode(raw, headers), resp.geturl()
            except urllib.error.HTTPError as e:
                last = e
                if e.code in (403, 412, 429, 503):
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise
            except Exception as e:
                last = e
                if attempt == 0:
                    time.sleep(1.5)
                    continue
                raise
        raise last

    def _extract(self, html, base_url):
        if not HAVE_LXML:
            return self._extract_stdlib(html, base_url)
        doc = lxml_html.fromstring(html, base_url=base_url)
        items = []
        seen = set()
        for a in doc.iter("a"):
            href = a.get("href")
            if not href:
                continue
            title = " ".join((a.text_content() or "").split())
            url = urljoin(base_url, href)
            if not url.startswith("http") or not title or len(title) < 4:
                continue
            path = urlparse(url).path or "/"
            if EXCLUDE_PATH.search(path) or url in seen:
                continue
            date = ""
            node = a
            for _ in range(4):
                if node is None:
                    break
                txt = " ".join((node.text_content() or "").split())
                m = DATE_RE.search(txt)
                if m:
                    date = "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
                    break
                node = node.getparent()
            seen.add(url)
            items.append({"title": title, "url": url, "date": date})
        return items

    def _extract_stdlib(self, html, base_url):
        """无 lxml 时的兜底解析（只取标题+链接，不解析日期）。"""
        from html.parser import HTMLParser

        class P(HTMLParser):
            def __init__(self):
                super().__init__()
                self.cur = None
                self.items = []
                self.buf = []

            def handle_starttag(self, tag, attrs):
                if tag.lower() == "a":
                    d = dict(attrs)
                    self.cur = d.get("href")
                    self.buf = []

            def handle_data(self, data):
                if self.cur is not None:
                    self.buf.append(data)

            def handle_endtag(self, tag):
                if tag.lower() == "a" and self.cur is not None:
                    title = " ".join("".join(self.buf).split())
                    self.items.append((title, self.cur))
                    self.cur = None

        p = P()
        p.feed(html)
        items = []
        for title, href in p.items:
            url = urljoin(base_url, href)
            if url.startswith("http") and title and len(title) >= 4:
                items.append({"title": title, "url": url, "date": ""})
        return items

    def _match_keywords(self, text):
        low = text.lower()
        return any(kw and kw.lower() in low for kw in config.SEARCH_KEYWORDS)

    def collect(self):
        sources = _load_sources()
        sources = [s for s in sources if s.get("enabled")]
        include = [x.strip() for x in config.SITE_NEWS_SOURCES.split(",") if x.strip()]
        if include:
            sources = [
                s for s in sources
                if any(
                    k in (s.get("province") or "") or k in (s.get("name") or "") or k in (s.get("category") or "")
                    for k in include
                )
            ]
        max_sites = config.SITE_NEWS_MAX_SITES
        if max_sites > 0:
            sources = sources[:max_sites]
        if not sources:
            print("[site_news] 没有可用的网站源（检查 site_sources.json 与 LIVE_SITE_NEWS_SOURCES）")
            return []

        records = []
        for s in sources:
            url = s.get("url") or ""
            if not url:
                continue
            try:
                html, final_url = self._fetch(url)
            except Exception as e:
                print(f"[site_news] {s.get('name')} 抓取失败: {e}")
                continue
            items = self._extract(html, final_url)
            hits = []
            seen = set()
            for it in items:
                if not self._match_keywords(it["title"]):
                    continue
                if it["url"] in seen:
                    continue
                seen.add(it["url"])
                hits.append(it)
            hits = hits[:config.SITE_NEWS_MAX_ITEMS]
            category = s.get("category") or ""
            is_gov = category in ("省政府门户", "省民宗委", "网信办/举报", "自治州/自治县政府")
            platform = "政务网站" if is_gov else "新闻网站"
            name = s.get("name") or urlparse(url).netloc
            province = s.get("province") or ""
            for it in hits:
                records.append({
                    "发布时间": it.get("date") or "",
                    "平台": platform,
                    "具体来源": f"{name}·首页",
                    "账号": name,
                    "正文": it["title"],
                    "原始链接": it["url"],
                    "地区": province,
                    "省份": province,
                    "城市": "",
                    "语言": "中文",
                    "总体态度": "待核实",
                    "点赞量": 0,
                    "评论量": 0,
                    "转发量": 0,
                    "是否重点": "否",
                    "是否计入统计": "是",
                    "备注": f"网站通用采集模板（{category}）；标题级采集，发布时间来自列表页；正文与态度待扩展",
                })
            print(f"[site_news] {name}：页面链接 {len(items)} 条，关键词命中 {len(hits)} 条")
            time.sleep(config.REQUEST_INTERVAL)
        return records

    def check(self):
        sources = [s for s in _load_sources() if s.get("enabled")]
        if not sources:
            print("[site_news] 没有已启用的网站源")
            return False
        url = sources[0]["url"]
        try:
            html, final = self._fetch(url)
            ok = bool(html and html.strip())
            print(f"[site_news] 连通性自检 OK：{sources[0].get('name')} -> {final}（{len(html)} 字符）")
            return ok
        except Exception as e:
            print(f"[site_news] 连通性自检失败：{url} -> {e}")
            return False

    def sample(self):
        return [
            {
                "发布时间": "2026-08-16 09:00:00",
                "平台": "新闻网站",
                "具体来源": "黄河新闻网·首页",
                "账号": "黄河新闻网",
                "正文": "山西各地掀起学习贯彻民族团结进步促进法热潮",
                "原始链接": "https://www.sxgov.cn/demo/0001",
                "地区": "山西",
                "省份": "山西",
                "语言": "中文",
                "总体态度": "待核实",
                "点赞量": 0,
                "评论量": 0,
                "转发量": 0,
                "是否重点": "否",
                "是否计入统计": "是",
                "备注": "collect.py --demo 示例记录（编造）",
            },
        ]


def _load_sources():
    path = config.SITE_NEWS_SOURCES_JSON
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    return data.get("sources", []) or []
