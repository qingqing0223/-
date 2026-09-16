# -*- coding: utf-8 -*-
"""采集器注册表"""
from collectors.base import BaseCollector
from collectors.file_watcher import FileWatcherCollector
from collectors.simulator import SimulatorCollector
from collectors.weibo import WeiboCollector
from collectors.douyin import DouyinCollector
from collectors.kuaishou import KuaishouCollector
from collectors.wechat import WechatCollector
from collectors.zhihu import ZhihuCollector
from collectors.baidu_zhidao import BaiduZhidaoCollector
from collectors.douban import DoubanCollector
from collectors.xiaohongshu import XiaohongshuCollector
from collectors.bilibili import BilibiliCollector
from collectors.reddit import RedditCollector
from collectors.site_news import SiteNewsCollector

COLLECTOR_CLASSES = [
    SimulatorCollector,
    FileWatcherCollector,
    WeiboCollector,
    DouyinCollector,
    KuaishouCollector,
    WechatCollector,
    ZhihuCollector,
    BaiduZhidaoCollector,
    DoubanCollector,
    XiaohongshuCollector,
    BilibiliCollector,
    RedditCollector,
    SiteNewsCollector,
]


def get_collectors():
    return {cls.name: cls() for cls in COLLECTOR_CLASSES}
