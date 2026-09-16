# -*- coding: utf-8 -*-
"""微信公众号采集器：搜狗微信文章搜索（无需登录，实测可用）

说明：
- 使用 https://weixin.sogou.com/weixin?type=2&query=关键词 搜索公众号文章；
- 返回标题、公众号名、发布时间、摘要、跳转链接（原始链接为搜狗跳转地址）；
- 搜狗有反爬验证码机制，采集间隔调得较大（默认 10 分钟一次，关键词间休息 5 秒）；
- 视频号暂无公开接口，仍走人工/第三方导出。
"""
import hashlib
import html
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime

import config
from collectors.base import BaseCollector, ts_iso

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _strip_tags(v):
    if v is None:
        return ""
    s = re.sub(r"<br\s*/?>", " ", str(v), flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", html.unescape(s))
    return s.strip()


class WechatCollector(BaseCollector):
    name = "wechat"
    label = "微信公众号/视频号"
    enabled = True
    interval = 600
    note = "搜狗微信文章搜索（无需登录，实测可用）；视频号暂无公开接口"

    def _fetch_page(self, keyword, page):
        params = {"type": "2", "query": keyword}
        if page > 1:
            params["page"] = page
        req = urllib.request.Request(
            "https://weixin.sogou.com/weixin?" + urllib.parse.urlencode(params),
            headers={"User-Agent": _UA, "Referer": "https://weixin.sogou.com/"},
        )
        with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="ignore")

    def _parse_page(self, page_html, keyword):
        if "请输入验证码" in page_html or "antispider" in page_html or "seccode" in page_html:
            raise RuntimeError("搜狗返回验证码页，触发风控，请降低频率后重试")
        items = re.findall(r'<li[^>]*id="sogou_vr_11002601_box_\d+"[\s\S]*?</li>', page_html)
        out = []
        for li in items:
            title_m = re.search(r'<h3>[\s\S]*?<a[^>]*>(.*?)</a>', li, re.S)
            title = _strip_tags(title_m.group(1)) if title_m else ""
            if not title:
                continue
            link_m = re.search(r'href="(/link\?[^"]+)"', li)
            link = html.unescape(link_m.group(1)) if link_m else ""
            account_m = re.search(r'<span class="all-time-y2">([^<]*)</span>', li)
            account = _strip_tags(account_m.group(1)) if account_m else ""
            time_m = re.search(r"timeConvert\('(\d+)'\)", li)
            published = ts_iso(time_m.group(1)) if time_m else ""
            snippet_m = re.search(r'<p class="txt-info"[\s\S]*?>(.*?)</p>', li, re.S)
            snippet = _strip_tags(snippet_m.group(1)) if snippet_m else ""
            text = title
            if snippet and snippet != title:
                text = f"{title}。{snippet}"
            key = "|".join([title, account, published])
            uid = "wechat-sogou-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
            out.append({
                "唯一编号": uid,
                "采集时间": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "发布时间": published,
                "平台": "微信公众号",
                "平台组": "微信公众号/视频号",
                "具体来源": f"搜狗微信搜索·{keyword}",
                "账号": account,
                "正文": text,
                "原始链接": ("https://weixin.sogou.com" + link) if link else "",
                "地区": "",
                "省份": "",
                "城市": "",
                "IP属地": "",
                "语言": "中文",
                "总体态度": "待核实",
                "具体问题类别": "-",
                "点赞量": 0,
                "评论量": 0,
                "转发量": 0,
                "是否重点": "否",
                "是否计入统计": "是",
                "备注": "搜狗微信文章搜索采集（标题+摘要）；无互动量；原始链接为搜狗跳转地址；态度待人工复核",
            })
        return out

    def collect(self):
        records = []
        seen = set()
        for keyword in config.SEARCH_KEYWORDS:
            try:
                for page in range(1, config.WECHAT_SOGOU_PAGES + 1):
                    page_html = self._fetch_page(keyword, page)
                    for rec in self._parse_page(page_html, keyword):
                        if rec["唯一编号"] in seen:
                            continue
                        seen.add(rec["唯一编号"])
                        records.append(rec)
                    time.sleep(config.WECHAT_SOGOU_INTERVAL)
            except Exception as e:
                print(f"[wechat] 搜狗关键词「{keyword}」失败: {e}")
                continue
        return records

    def check(self):
        if not config.SEARCH_KEYWORDS:
            print("[wechat] SEARCH_KEYWORDS 为空，无法测试")
            return False
        kw = config.SEARCH_KEYWORDS[0]
        try:
            page_html = self._fetch_page(kw, 1)
            records = self._parse_page(page_html, kw)
            print(f"[wechat] 搜狗微信搜索可达，关键词「{kw}」返回 {len(records)} 条文章")
            for r in records[:5]:
                print("   ", r["发布时间"], r["账号"], r["正文"][:36])
            return True
        except Exception as e:
            print("[wechat] 搜狗微信搜索失败:", e)
            return False

    def sample(self):
        return [
            {
                "发布时间": "2026-08-14 08:55:00",
                "平台": "微信公众号",
                "具体来源": "本地融媒文章评论区",
                "账号": "示例公众号D",
                "正文": "希望执法不要走过场，真正保护少数民族就业权益。",
                "原始链接": "https://mp.weixin.qq.com/demo/0004",
                "地区": "甘肃",
                "地区组": "四川、甘肃民族地区",
                "省份": "甘肃",
                "城市": "兰州",
                "IP属地": "甘肃",
                "语言": "中文",
                "总体态度": "担忧影响",
                "具体问题类别": "担忧影响",
                "点赞量": 5,
                "评论量": 2,
                "转发量": 0,
                "是否重点": "否",
                "是否计入统计": "是",
                "备注": "collect.py --demo 示例记录（编造）",
            },
            {
                "发布时间": "2026-08-14 10:15:00",
                "平台": "微信公众号",
                "具体来源": "公众号评论区",
                "账号": "示例账号K",
                "正文": "请问促进法对少数民族传统节日有什么规定？",
                "原始链接": "https://mp.weixin.qq.com/demo/0011",
                "地区": "广西",
                "地区组": "广西",
                "省份": "广西",
                "城市": "南宁",
                "IP属地": "广西",
                "语言": "中文",
                "总体态度": "咨询疑问",
                "具体问题类别": "咨询疑问",
                "点赞量": 3,
                "评论量": 1,
                "转发量": 0,
                "是否重点": "否",
                "是否计入统计": "是",
                "备注": "collect.py --demo 示例记录（编造）",
            },
        ]
