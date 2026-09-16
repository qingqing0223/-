# -*- coding: utf-8 -*-
"""抖音采集器：热榜公开接口（无需登录，实测可用）

说明：
- 使用抖音网页热榜接口 https://www.douyin.com/aweme/v1/web/hot/search/list/
- 关键词搜索接口实测返回“请先登录，再继续搜索吧”，暂未接入；
- 每个命中话题按“一条舆情”入库，热度值默认近似填入点赞量（DOUYIN_HOT_AS_LIKES=1）。
"""
import hashlib
import urllib.parse
from datetime import datetime

import config
from collectors.base import BaseCollector, http_get_json, ts_iso

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _clean(v):
    if v is None:
        return ""
    return str(v).replace("\u3000", " ").replace("\xa0", " ").strip()


class DouyinCollector(BaseCollector):
    name = "douyin"
    label = "抖音等视频平台"
    enabled = True
    interval = 300
    note = "抖音热榜公开接口（无需登录，实测可用）；关键词搜索需登录，暂未接入"

    def _request_hot(self):
        params = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "pc_client_type": "1",
            "version_code": "170400",
            "version_name": "17.4.0",
            "cookie_enabled": "true",
            "screen_width": "1536",
            "screen_height": "864",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "126.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "126.0.0.0",
            "os_name": "Windows",
            "os_version": "10",
            "platform": "PC",
        }
        data = http_get_json(
            "https://www.douyin.com/aweme/v1/web/hot/search/list/",
            params=params,
            headers={"User-Agent": _UA, "Referer": "https://www.douyin.com/"},
            timeout=config.HTTP_TIMEOUT,
        )
        if data.get("status_code") != 0:
            raise RuntimeError(f"抖音热榜返回 status_code={data.get('status_code')}: {data.get('status_msg')}")
        return (data.get("data") or {}).get("word_list") or []

    def _collect_hot(self):
        kws = config.DOUYIN_HOT_KEYWORDS
        if not kws:
            print("[douyin] DOUYIN_HOT_KEYWORDS 为空，跳过抖音热榜采集")
            return []
        items = self._request_hot()
        out = []
        seen = set()
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        day = now[:10]
        for it in items:
            word = _clean(it.get("word"))
            if not word:
                continue
            if not any(k in word for k in kws):
                continue
            key = f"{word}|{day}"
            if key in seen:
                continue
            seen.add(key)
            position = int(it.get("position") or 0) or len(out) + 1
            hot_value = int(it.get("hot_value") or 0)
            view_count = int(it.get("view_count") or 0)
            video_count = int(it.get("video_count") or 0)
            discuss_count = int(it.get("discuss_video_count") or 0)
            event_time = ts_iso(it.get("event_time")) or now
            uid = "douyin-hot-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
            out.append({
                "唯一编号": uid,
                "采集时间": now,
                "发布时间": event_time,
                "平台": "抖音",
                "平台组": "抖音等视频平台",
                "具体来源": f"抖音热榜·第{position}位",
                "账号": "",
                "正文": word,
                "原始链接": "https://www.douyin.com/search/" + urllib.parse.quote(word),
                "地区": "",
                "省份": "",
                "城市": "",
                "IP属地": "",
                "语言": "中文",
                "总体态度": "待核实",
                "具体问题类别": "-",
                "点赞量": hot_value if config.DOUYIN_HOT_AS_LIKES else 0,
                "评论量": 0,
                "转发量": 0,
                "是否重点": "是" if position <= 10 else "否",
                "是否计入统计": config.DOUYIN_HOT_COUNTED,
                "备注": (
                    f"抖音热榜快照 {now}，第{position}位，热度值{hot_value}（非点赞量）；"
                    f"话题视频{video_count}个，讨论视频{discuss_count}个，浏览量{view_count}；态度待人工复核"
                ),
            })
        return out

    def collect(self):
        try:
            return self._collect_hot()
        except Exception as e:
            print(f"[douyin] 热榜采集失败: {e}")
            return []

    def check(self):
        ok = True
        try:
            items = self._request_hot()
            kws = config.DOUYIN_HOT_KEYWORDS
            matched = [it for it in items if any(k in (it.get("word") or "") for k in kws)] if kws else []
            print(f"[douyin] 热榜公开接口可达，热榜共 {len(items)} 条，命中关键词 {len(matched)} 条")
            for it in matched[:5]:
                print("   ", it.get("position"), it.get("word"), it.get("hot_value"))
            if not kws:
                print("   提示：DOUYIN_HOT_KEYWORDS 为空，不会采到热榜内容")
        except Exception as e:
            print("[douyin] 热榜公开接口失败:", e)
            ok = False
        print("[douyin] 关键词搜索：实测需登录，暂未接入")
        return ok

    def sample(self):
        return [
            {
                "发布时间": "2026-08-14 10:02:00",
                "平台": "抖音",
                "具体来源": "抖音·普法视频评论区",
                "账号": "示例账号B",
                "正文": "请问促进法对少数民族学生升学、就业有什么具体保护措施？",
                "原始链接": "https://douyin.com/demo/0002",
                "地区": "新疆",
                "地区组": "新疆",
                "省份": "新疆",
                "城市": "乌鲁木齐",
                "IP属地": "新疆",
                "语言": "中文",
                "总体态度": "咨询疑问",
                "具体问题类别": "咨询疑问",
                "点赞量": 12,
                "评论量": 3,
                "转发量": 0,
                "是否重点": "否",
                "是否计入统计": "是",
                "备注": "collect.py --demo 示例记录（编造）",
            },
            {
                "发布时间": "2026-08-14 10:08:00",
                "平台": "抖音",
                "具体来源": "抖音·视频评论区",
                "账号": "示例用户I",
                "正文": "我们厂里招聘现在没那么多条条框框了，支持。",
                "原始链接": "https://douyin.com/demo/0009",
                "地区": "四川",
                "地区组": "四川、甘肃民族地区",
                "省份": "四川",
                "城市": "凉山",
                "IP属地": "四川",
                "语言": "中文",
                "总体态度": "支持认可",
                "具体问题类别": "-",
                "点赞量": 152,
                "评论量": 20,
                "转发量": 3,
                "是否重点": "否",
                "是否计入统计": "是",
                "备注": "collect.py --demo 示例记录（编造）",
            },
        ]
