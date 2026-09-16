# -*- coding: utf-8 -*-
"""豆瓣采集器：小组讨论搜索（公开页，无需登录，实测可用）

说明：
- 使用 https://www.douban.com/group/search?cat=1013&q=关键词&sort=time 搜索小组讨论；
- 每条结果取：帖子标题、话题链接、发布时间、回复数、所属小组；
- 列表页没有正文摘要/作者，正文暂用标题；打开话题页可扩展正文（待扩展）；
- 回复数如实填入“评论量”（备注说明来自列表页），点赞/转发记 0。
"""
import hashlib
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime

import config
from collectors.base import BaseCollector

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _strip_tags(v):
    if v is None:
        return ""
    s = re.sub(r"<br\s*/?>", " ", str(v), flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


class DoubanCollector(BaseCollector):
    name = "douban"
    label = "豆瓣"
    enabled = True
    interval = 600
    note = "豆瓣小组讨论搜索公开页（无需登录，实测可用）；小红书搜索需登录+签名，另行评估"

    def _fetch(self, keyword, page):
        params = {"cat": "1013", "q": keyword, "sort": "time"}
        if page > 1:
            params["start"] = (page - 1) * 10
        req = urllib.request.Request(
            "https://www.douban.com/group/search?" + urllib.parse.urlencode(params),
            headers={"User-Agent": _UA, "Referer": "https://www.douban.com/group/explore"},
        )
        with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="ignore")

    def _parse_page(self, page_html, keyword):
        if "没有找到与" in page_html and "相关的内容" in page_html:
            return []
        rows = re.findall(r'<tr class="pl">[\s\S]*?</tr>', page_html)
        out = []
        for tr in rows:
            link_m = re.search(r'<a[^>]*href="(https://www\.douban\.com/group/topic/\d+/)[^"]*"[^>]*title="([^"]*)"', tr)
            link = link_m.group(1) if link_m else ""
            title = _strip_tags(link_m.group(2)) if link_m and link_m.lastindex and link_m.lastindex >= 2 else ""
            if not title:
                a_m = re.search(r'<a[^>]*>(.*?)</a>', tr, re.S)
                title = _strip_tags(a_m.group(1)) if a_m else ""
            if not title:
                continue
            time_m = re.search(r'<td class="td-time" title="([^"]+)"', tr)
            published = ""
            if time_m:
                try:
                    published = datetime.strptime(
                        time_m.group(1).strip(), "%Y-%m-%d %H:%M:%S"
                    ).strftime("%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    published = ""
            reply_m = re.search(r"(\d+)\s*回复", tr)
            reply_count = int(reply_m.group(1)) if reply_m else 0
            group_m = re.search(r'group/\d+/"[^>]*>([^<]+)</a>', tr)
            group = _strip_tags(group_m.group(1)) if group_m else ""
            uid = "douban-group-" + hashlib.sha1(
                (link or title + "|" + published).encode("utf-8")
            ).hexdigest()[:12]
            out.append({
                "唯一编号": uid,
                "采集时间": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "发布时间": published,
                "平台": "豆瓣",
                "平台组": "小红书/豆瓣等平台",
                "具体来源": f"豆瓣小组讨论搜索·{keyword}",
                "账号": group,
                "正文": title,
                "原始链接": link,
                "地区": "",
                "省份": "",
                "城市": "",
                "IP属地": "",
                "语言": "中文",
                "总体态度": "待核实",
                "具体问题类别": "-",
                "点赞量": 0,
                "评论量": reply_count,
                "转发量": 0,
                "是否重点": "否",
                "是否计入统计": "是",
                "备注": f"豆瓣小组讨论列表页采集（仅标题，{reply_count}回复来自列表页）；正文待扩展；态度待人工复核",
            })
        return out

    def collect(self):
        records = []
        seen = set()
        for keyword in config.SEARCH_KEYWORDS:
            try:
                for page in range(1, config.DOUBAN_GROUP_PAGES + 1):
                    page_html = self._fetch(keyword, page)
                    for rec in self._parse_page(page_html, keyword):
                        if rec["唯一编号"] in seen:
                            continue
                        seen.add(rec["唯一编号"])
                        records.append(rec)
                    time.sleep(config.DOUBAN_GROUP_INTERVAL)
            except Exception as e:
                print(f"[douban] 关键词「{keyword}」失败: {e}")
                continue
        return records

    def check(self):
        if not config.SEARCH_KEYWORDS:
            print("[douban] SEARCH_KEYWORDS 为空，无法测试")
            return False
        kw = config.SEARCH_KEYWORDS[0]
        try:
            page_html = self._fetch(kw, 1)
            records = self._parse_page(page_html, kw)
            print(f"[douban] 小组讨论搜索可达，关键词「{kw}」返回 {len(records)} 条帖子")
            for r in records[:5]:
                print("   ", r["发布时间"], r["账号"], r["正文"][:30], "| 回复", r["评论量"])
            return True
        except Exception as e:
            print("[douban] 小组讨论搜索失败:", e)
            return False

    def sample(self):
        return [
            {
                "发布时间": "2026-08-14 09:30:00",
                "平台": "豆瓣",
                "具体来源": "豆瓣小组讨论搜索·民族团结进步促进法",
                "账号": "示例小组",
                "正文": "有朋友了解民族团结进步促进法在基层怎么落实吗？",
                "原始链接": "https://www.douban.com/group/demo/0001",
                "地区": "",
                "省份": "",
                "城市": "",
                "IP属地": "",
                "语言": "中文",
                "总体态度": "咨询疑问",
                "具体问题类别": "咨询疑问",
                "点赞量": 0,
                "评论量": 3,
                "转发量": 0,
                "是否重点": "否",
                "是否计入统计": "是",
                "备注": "collect.py --demo 示例记录（编造）",
            },
        ]
