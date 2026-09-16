# -*- coding: utf-8 -*-
"""模拟采集器：用于验证「采集→入库→重算→前端实时推送」全链路，接入真实渠道后应关闭"""
import random
from datetime import datetime, timedelta

from collectors.base import BaseCollector
from config import SIM_BATCH_MAX, SIM_BATCH_MIN

PLATFORMS = ["微博", "抖音", "快手", "微信视频号", "微信公众号", "知乎", "B站", "小红书", "今日头条", "贴吧"]
REGIONS = ["四川", "甘肃", "新疆", "青海", "西藏", "云南", "内蒙古", "天津", "北京", "河南"]
ACCOUNTS = ["实时监测号", "本地资讯", "民族之声", "普法小助手", "网友小明", "陇上人家", "天山来客"]

TEMPLATES = [
    ("支持认可", "中文", "网友评论：民族团结进步促进法实施后，{region}群众反响热烈，大家都很支持。"),
    ("支持认可", "中文", "支持民族团结进步促进法，各民族要像石榴籽一样紧紧抱在一起。"),
    ("咨询疑问", "中文", "请问促进法对{region}少数民族学生在升学、就业方面有哪些具体保护措施？"),
    ("咨询疑问", "维吾尔语", "（维吾尔语评论，模拟采集）促进法在{region}落地后，群众想了解具体申请渠道。"),
    ("担忧影响", "中文", "希望{region}执行不要走过场，真正把促进法落到基层。"),
    ("担忧影响", "藏语", "（藏语评论，模拟采集）希望普法宣传能覆盖偏远牧区。"),
    ("参与建议", "中文", "建议在{region}多开展双语普法活动，让更多群众了解促进法。"),
    ("明确批评", "中文", "个别地方招聘仍存在民族歧视现象，希望按促进法严肃处理。"),
    ("歧视偏见", "中文", "反映{region}某公司招聘歧视少数民族，已附截图，请核实。"),
    ("公平争议", "中文", "讨论：促进法落实中如何保证各民族机会公平？"),
]


class SimulatorCollector(BaseCollector):
    name = "simulator"
    label = "模拟采集器（演示）"
    enabled = True
    interval = 12
    note = "演示用：按固定节奏生成模拟舆情，验证实时链路；接入真实渠道后请关闭"

    def collect(self):
        now = datetime.now()
        n = random.randint(SIM_BATCH_MIN, SIM_BATCH_MAX)
        records = []
        for _ in range(n):
            attitude, lang, tpl = random.choice(TEMPLATES)
            region = random.choice(REGIONS)
            platform = random.choice(PLATFORMS)
            published = now - timedelta(minutes=random.randint(0, 60))
            records.append({
                "发布时间": published.strftime("%Y-%m-%d %H:%M:%S"),
                "平台": platform,
                "账号": random.choice(ACCOUNTS) + str(random.randint(1, 999)),
                "正文": tpl.format(region=region),
                "地区": region,
                "省份": region,
                "语言": lang,
                "总体态度": attitude,
                "原始链接": f"https://example.com/sim/{now.strftime('%Y%m%d%H%M%S')}-{random.randint(1000,9999)}",
                "点赞量": random.randint(0, 5000),
                "评论量": random.randint(0, 800),
                "转发量": random.randint(0, 500),
                "其他备注": "模拟采集数据（演示）",
            })
        return records
