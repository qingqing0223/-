# -*- coding: utf-8 -*-
"""Reddit 采集器：优先官方 OAuth API，未配置密钥时回退到公开 JSON 搜索

说明：
- 配置 REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET 后走 https://oauth.reddit.com；
- 未配置时使用 https://www.reddit.com/search.json（无需登录，但限速更严格）；
- 正文 = 帖子正文（无正文时用标题）；语言按是否含中文简单判断。
"""
import base64
import json
import re
import time
import urllib.parse
import urllib.request

import config
from collectors.base import BaseCollector, http_get_json, ts_iso


class RedditCollector(BaseCollector):
    name = "reddit"
    label = "Reddit/海外"
    # 默认关闭：当前监控以国内平台为主（微博/B站/文件导出已够用）。
    # 如后续需要海外舆情，配置密钥后把这里改为 True 即可，其余代码无需改动。
    enabled = False
    interval = 300
    note = "默认关闭（国内平台已覆盖）；需要海外舆情时配置密钥并改 enabled=True"

    _token = None

    def _oauth_token(self):
        if self._token:
            return self._token
        auth = base64.b64encode(
            f"{config.REDDIT_CLIENT_ID}:{config.REDDIT_CLIENT_SECRET}".encode()
        ).decode()
        req = urllib.request.Request(
            "https://www.reddit.com/api/v1/access_token",
            data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
            headers={"Authorization": f"Basic {auth}", "User-Agent": config.REDDIT_USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT) as resp:
            self._token = json.loads(resp.read().decode("utf-8"))["access_token"]
        return self._token

    def _headers(self):
        h = {"User-Agent": config.REDDIT_USER_AGENT}
        if config.REDDIT_CLIENT_ID and config.REDDIT_CLIENT_SECRET:
            h["Authorization"] = f"bearer {self._oauth_token()}"
        return h

    def _search(self, keyword):
        if config.REDDIT_CLIENT_ID and config.REDDIT_CLIENT_SECRET:
            url = "https://oauth.reddit.com/search"
        else:
            url = "https://www.reddit.com/search.json"
        params = {"q": keyword, "limit": config.MAX_RESULTS, "sort": "new"}
        data = http_get_json(url, params=params, headers=self._headers(), timeout=config.HTTP_TIMEOUT)
        return (data.get("data") or {}).get("children") or []

    def check(self):
        """自检：密钥是否配置、OAuth token 能否获取（不采集数据）"""
        print("[reddit] REDDIT_CLIENT_ID 已配置:", "是" if config.REDDIT_CLIENT_ID else "否")
        print("[reddit] REDDIT_CLIENT_SECRET 已配置:", "是" if config.REDDIT_CLIENT_SECRET else "否")
        print("[reddit] User-Agent:", config.REDDIT_USER_AGENT)
        if not config.REDDIT_CLIENT_ID or not config.REDDIT_CLIENT_SECRET:
            print("[reddit] 未配置密钥：请先填写 03_live_system/.env 后重试")
            return False
        try:
            token = self._oauth_token()
            print("[reddit] OAuth token 获取成功（长度", len(token), "）")
            return True
        except Exception as e:
            print("[reddit] OAuth token 获取失败:", e)
            print("[reddit] 请检查 client_id / secret 是否复制正确、账号是否正常")
            return False

    def collect(self):
        records = []
        seen = set()
        for keyword in config.SEARCH_KEYWORDS:
            try:
                children = self._search(keyword)
            except Exception as e:
                print(f"[reddit] 关键词「{keyword}」失败: {e}")
                continue
            for child in children:
                d = child.get("data") or {}
                permalink = d.get("permalink") or ""
                if not permalink or permalink in seen:
                    continue
                title = re.sub(r"<[^>]+>", "", str(d.get("title") or "")).strip()
                selftext = re.sub(r"<[^>]+>", "", str(d.get("selftext") or "")).strip()
                text = selftext or title
                if not text:
                    continue
                if not any(kw in text for kw in config.SEARCH_KEYWORDS):
                    continue
                seen.add(permalink)
                lang = "中文" if re.search(r"[\u4e00-\u9fff]", text) else "英语"
                records.append({
                    "发布时间": ts_iso(d.get("created_utc")),
                    "平台": "Reddit",
                    "具体来源": f"Reddit搜索·{keyword}",
                    "账号": str(d.get("author") or "").strip(),
                    "正文": text,
                    "原始链接": f"https://www.reddit.com{permalink}",
                    "地区": "",
                    "语言": lang,
                    "总体态度": "待核实",
                    "点赞量": int(d.get("score") or 0),
                    "评论量": int(d.get("num_comments") or 0),
                    "转发量": int(d.get("num_crossposts") or 0),
                    "是否重点": "否",
                    "是否计入统计": "是",
                    "备注": "Reddit搜索接口采集；态度待人工复核",
                })
            time.sleep(config.REQUEST_INTERVAL)
        return records
