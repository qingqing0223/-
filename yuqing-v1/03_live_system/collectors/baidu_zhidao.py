# -*- coding: utf-8 -*-
"""百度知道采集器：搜索页公开 HTML（无需登录，实测可用）

说明：
- 使用 https://zhidao.baidu.com/search?word=关键词 搜索问答；
- 每条结果取：问题标题、最佳回答摘要、回答日期、回答者、回答数、问题链接；
- 无点赞/评论/转发字段，互动量记 0，回答数写入备注；
- 百度知道对高频请求有验证码风控，默认 10 分钟一次、关键词间休息 5 秒。
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


def _parse_date(v):
    s = _strip_tags(v)
    if not s:
        return ""
    s = s.replace("年", "-").replace("月", "-").replace("日", "")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
    return ""


class BaiduZhidaoCollector(BaseCollector):
    name = "baidu_zhidao"
    label = "百度知道"
    enabled = True
    interval = 600
    note = "百度知道搜索公开页（无需登录，实测可用）；知乎实测被登录墙/风控拦截，暂未接入"

    def _fetch(self, keyword, page):
        params = {
            "lm": "0",
            "rn": "10",
            "pn": str((page - 1) * 10),
            "fr": "search",
            "ie": "utf8",
            "word": keyword,
        }
        req = urllib.request.Request(
            "https://zhidao.baidu.com/search?" + urllib.parse.urlencode(params),
            headers={"User-Agent": _UA, "Referer": "https://zhidao.baidu.com/"},
        )
        with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="ignore")

    def _parse_page(self, page_html, keyword):
        if "安全验证" in page_html or "验证码" in page_html or "antispider" in page_html:
            raise RuntimeError("百度知道返回安全验证页，触发风控，请降低频率后重试")
        blocks = re.findall(r'<dl class="dl"[\s\S]*?</dl>', page_html)
        out = []
        for dl in blocks:
            link_m = re.search(r'<a[^>]*href="(http[^"]+)"[^>]*class="ti"', dl)
            title_m = re.search(r'class="ti"[^>]*>(.*?)</a>', dl, re.S)
            title = _strip_tags(title_m.group(1)) if title_m else ""
            link = link_m.group(1) if link_m else ""
            if not title:
                continue
            qid_m = re.search(r"data-rank=\"\d+:(\d+)\"", dl)
            qid = qid_m.group(1) if qid_m else ""
            answer_m = re.search(r'<dd class="dd answer"[^>]*>(.*?)</dd>', dl, re.S)
            answer = _strip_tags(answer_m.group(1)) if answer_m else ""
            answer = re.sub(r"^答：", "", answer).strip()
            date_m = re.search(r'<span class="mr-7">([^<]*)</span>', dl)
            published = _parse_date(date_m.group(1)) if date_m else ""
            account_m = re.search(r"回答者:[\s\S]*?<a[^>]*>(.*?)</a>", dl)
            account = _strip_tags(account_m.group(1)) if account_m else ""
            count_m = re.search(r"(\d+)\s*个回答", dl)
            answer_count = int(count_m.group(1)) if count_m else 0
            text = title
            if answer and answer != title:
                text = f"{title}。{answer}"
            uid = "baidu-zhidao-" + hashlib.sha1(
                (qid or title + "|" + published).encode("utf-8")
            ).hexdigest()[:12]
            out.append({
                "唯一编号": uid,
                "采集时间": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "发布时间": published,
                "平台": "百度知道",
                "平台组": "知乎/B站/百度知道",
                "具体来源": f"百度知道搜索·{keyword}",
                "账号": account,
                "正文": text,
                "原始链接": link,
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
                "备注": f"百度知道搜索采集（标题+最佳回答摘要），{answer_count}个回答；无互动量；态度待人工复核",
            })
        return out

    def collect(self):
        records = []
        seen = set()
        for keyword in config.SEARCH_KEYWORDS:
            try:
                for page in range(1, config.BAIDU_ZHIDAO_PAGES + 1):
                    page_html = self._fetch(keyword, page)
                    for rec in self._parse_page(page_html, keyword):
                        if rec["唯一编号"] in seen:
                            continue
                        seen.add(rec["唯一编号"])
                        records.append(rec)
                    time.sleep(config.BAIDU_ZHIDAO_INTERVAL)
            except Exception as e:
                print(f"[baidu_zhidao] 关键词「{keyword}」失败: {e}")
                continue
        return records

    def check(self):
        if not config.SEARCH_KEYWORDS:
            print("[baidu_zhidao] SEARCH_KEYWORDS 为空，无法测试")
            return False
        kw = config.SEARCH_KEYWORDS[0]
        try:
            page_html = self._fetch(kw, 1)
            records = self._parse_page(page_html, kw)
            print(f"[baidu_zhidao] 搜索页可达，关键词「{kw}」返回 {len(records)} 条问答")
            for r in records[:5]:
                print("   ", r["发布时间"], r["账号"], r["正文"][:36])
            return True
        except Exception as e:
            print("[baidu_zhidao] 搜索失败:", e)
            return False

    def sample(self):
        return [
            {
                "发布时间": "2026-08-14 09:20:00",
                "平台": "百度知道",
                "具体来源": "百度知道搜索·民族团结进步促进法",
                "账号": "示例答主",
                "正文": "民族团结进步促进法是一部为铸牢中华民族共同体意识提供法治保障的法律。支持。",
                "原始链接": "https://zhidao.baidu.com/demo/0001",
                "地区": "",
                "省份": "",
                "城市": "",
                "IP属地": "",
                "语言": "中文",
                "总体态度": "支持认可",
                "具体问题类别": "-",
                "点赞量": 0,
                "评论量": 0,
                "转发量": 0,
                "是否重点": "否",
                "是否计入统计": "是",
                "备注": "collect.py --demo 示例记录（编造）",
            },
        ]
