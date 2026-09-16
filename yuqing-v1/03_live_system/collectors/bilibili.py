# -*- coding: utf-8 -*-
"""哔哩哔哩采集器：使用 B站公开搜索接口（无需登录）

说明：
- 搜索“民族团结进步促进法 / 民族团结 / 民族歧视”等关键词的视频；
- 正文 = 视频标题 + 简介（评论逐条采集待扩展）；
- 默认每个视频再请求一次 view 接口补充点赞/评论/转发（可关闭）。
"""
import re
import time
import urllib.error

import config
from collectors.base import BaseCollector, http_get_json, ts_iso


class BilibiliCollector(BaseCollector):
    name = "bilibili"
    label = "哔哩哔哩"
    enabled = True
    interval = 300
    note = "B站公开搜索接口（无需登录）；评论逐条采集待扩展"

    _cookie = None

    def _ensure_cookie(self):
        if self._cookie is not None:
            return self._cookie
        try:
            data = http_get_json("https://api.bilibili.com/x/frontend/finger/spi", timeout=config.HTTP_TIMEOUT)
            payload = data.get("data") or {}
            parts = []
            if payload.get("b_3"):
                parts.append(f"buvid3={payload['b_3']}")
            if payload.get("b_4"):
                parts.append(f"buvid4={payload['b_4']}")
            self._cookie = "; ".join(parts)
        except Exception:
            self._cookie = ""
        return self._cookie

    def _headers(self):
        h = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Referer": "https://www.bilibili.com/",
        }
        cookie = self._ensure_cookie()
        if cookie:
            h["Cookie"] = cookie
        return h

    def _request_json(self, url, params=None):
        """带 412/429/5xx 重试的 JSON 请求（触发风控时刷新指纹后重试）"""
        last = None
        for attempt in range(3):
            try:
                data = http_get_json(url, params=params, headers=self._headers(), timeout=config.HTTP_TIMEOUT)
                code = data.get("code")
                if code in (0, None):
                    return data
                if code == -412:
                    raise RuntimeError("B站风控 code=-412")
                raise RuntimeError(f"B站接口返回 code={code}: {data.get('message')}")
            except urllib.error.HTTPError as e:
                last = e
                if e.code in (412, 429, 403, 502, 503):
                    wait = 3 * (attempt + 1)
                    print(f"[bilibili] 触发 HTTP {e.code}，{wait} 秒后重试")
                    time.sleep(wait)
                    self._cookie = None
                    continue
                raise
            except Exception as e:
                last = e
                if "412" in str(e) or "-412" in str(e):
                    wait = 3 * (attempt + 1)
                    print(f"[bilibili] 风控拦截，{wait} 秒后重试")
                    time.sleep(wait)
                    self._cookie = None
                    continue
                raise
        raise last

    def _search(self, keyword):
        url = "https://api.bilibili.com/x/web-interface/search/type"
        params = {"search_type": "video", "keyword": keyword, "page": 1}
        data = self._request_json(url, params=params)
        return (data.get("data") or {}).get("result") or []

    def _view_stats(self, bvid):
        try:
            data = http_get_json(
                "https://api.bilibili.com/x/web-interface/view",
                params={"bvid": bvid},
                headers=self._headers(),
                timeout=config.HTTP_TIMEOUT,
            )
            stat = (data.get("data") or {}).get("stat") or {}
            return {
                "like": stat.get("like") or 0,
                "reply": stat.get("reply") or 0,
                "share": stat.get("share") or 0,
            }
        except Exception:
            return {}

    def collect(self):
        records = []
        seen = set()
        for keyword in config.SEARCH_KEYWORDS:
            try:
                items = self._search(keyword)
            except Exception as e:
                print(f"[bilibili] 关键词「{keyword}」失败: {e}")
                continue
            count = 0
            for item in items:
                if count >= config.MAX_RESULTS:
                    break
                bvid = item.get("bvid") or ""
                if not bvid or bvid in seen:
                    continue
                seen.add(bvid)
                count += 1
                title = re.sub(r"<[^>]+>", "", str(item.get("title") or "")).strip()
                desc = str(item.get("description") or "").strip()
                text = title
                if desc and desc not in title:
                    text = f"{title}。{desc}" if title else desc
                stat = {}
                if config.BILIBILI_ENRICH_STATS:
                    stat = self._view_stats(bvid)
                    time.sleep(config.REQUEST_INTERVAL)
                records.append({
                    "发布时间": ts_iso(item.get("pubdate")),
                    "平台": "B站",
                    "具体来源": f"B站搜索·{keyword}",
                    "账号": str(item.get("author") or "").strip(),
                    "正文": text,
                    "原始链接": str(item.get("arcurl") or f"https://www.bilibili.com/video/{bvid}"),
                    "地区": "",
                    "语言": "中文",
                    "总体态度": "待核实",
                    "点赞量": stat.get("like", 0),
                    "评论量": stat.get("reply", 0),
                    "转发量": stat.get("share", 0),
                    "是否重点": "否",
                    "是否计入统计": "是",
                    "备注": "B站公开搜索接口采集（标题+简介）；评论逐条采集待扩展；态度待人工复核",
                })
            time.sleep(config.REQUEST_INTERVAL)
        return records

    def sample(self):
        return [
            {
                "发布时间": "2026-08-14 09:58:00",
                "平台": "今日头条",
                "具体来源": "今日头条·新闻评论区",
                "账号": "示例用户H",
                "正文": "促进法很好，建议多开展双语普法宣传。",
                "原始链接": "https://toutiao.com/demo/0008",
                "地区": "西藏",
                "地区组": "青海、西藏",
                "省份": "西藏",
                "城市": "拉萨",
                "IP属地": "西藏",
                "语言": "藏语",
                "总体态度": "参与建议",
                "具体问题类别": "参与建议",
                "点赞量": 23,
                "评论量": 4,
                "转发量": 1,
                "是否重点": "否",
                "是否计入统计": "是",
                "备注": "collect.py --demo 示例记录（编造）",
            },
        ]
