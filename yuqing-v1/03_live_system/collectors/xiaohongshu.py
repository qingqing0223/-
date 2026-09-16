# -*- coding: utf-8 -*-
"""小红书采集器（占位）：搜索需登录+签名，暂无法无登录接入

实测结论：
- 搜索页 /search_result 可打开但 SSR 不含结果，结果由登录态+签名 API 加载；
- 搜索 API edith.xiaohongshu.com 直接请求 404；
- 探索页 /explore 可无登录读到 28 条推荐笔记（标题/点赞/作者），
  但为随机推荐流、无法按关键词检索，实测命中民族关键词 0 条；
- 结论：暂走人工/第三方导出（inbox/），后续评估浏览器 Cookie 方案。
"""
from collectors.base import BaseCollector


class XiaohongshuCollector(BaseCollector):
    name = "xiaohongshu"
    label = "小红书"
    enabled = False
    interval = 600
    note = "已实测：搜索需登录+签名、API 404；探索流无关键词命中；暂走人工导出"

    def collect(self):
        return []

    def sample(self):
        return [
            {
                "发布时间": "2026-08-14 10:20:00",
                "平台": "小红书",
                "具体来源": "小红书·笔记评论区",
                "账号": "示例用户L",
                "正文": "促进法对少数民族地区就业有哪些支持？求科普。",
                "原始链接": "https://xiaohongshu.com/demo/0012",
                "地区": "云南",
                "地区组": "云南东中部民族地区",
                "省份": "云南",
                "城市": "大理",
                "IP属地": "云南",
                "语言": "中文",
                "总体态度": "咨询疑问",
                "具体问题类别": "咨询疑问",
                "点赞量": 45,
                "评论量": 12,
                "转发量": 2,
                "是否重点": "否",
                "是否计入统计": "是",
                "备注": "collect.py --demo 示例记录（编造）",
            },
        ]
