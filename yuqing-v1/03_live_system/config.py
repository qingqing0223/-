# -*- coding: utf-8 -*-
"""实时态势感知系统配置（全部可用环境变量覆盖）"""
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
WEB_DIR = os.path.join(BASE_DIR, "web")
INBOX_DIR = os.path.join(BASE_DIR, "inbox")
PROCESSED_DIR = os.path.join(INBOX_DIR, "processed")


def _load_dotenv(path):
    """极简 .env 加载：真实环境变量优先，文件里 KEY=VALUE 每行一条"""
    if not path or not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)


# 支持用 .env 存放密钥（默认 03_live_system/.env，可用 LIVE_DOTENV 指定）
_load_dotenv(os.getenv("LIVE_DOTENV") or os.path.join(BASE_DIR, ".env"))

DB_PATH = os.getenv("LIVE_DB_PATH", os.path.join(DATA_DIR, "live.db"))
HOST = os.getenv("LIVE_HOST", "127.0.0.1")
PORT = int(os.getenv("LIVE_PORT", "8765"))

BASE_DATA_JS = os.getenv(
    "BASE_DATA_JS",
    os.path.join(WEB_DIR, "assets", "data.js"),
)

# ---------------- 统计口径（预热阶段） ----------------
# 大屏正式预热阶段只统计“实际入库”的数据，与第一阶段历史基线（data.js / origin=history）
# 以及此前的测试数据隔离。可在 03_live_system/phase.json 中修改，也可用环境变量临时覆盖：
#   LIVE_STATS_START=2026-09-16T00:00:00   只统计该时间点之后入库的数据；off/空 表示不过滤
#   LIVE_INCLUDE_HISTORY=1                 把第一阶段历史基线一起算进大屏（默认 0，不参与展示）
PHASE_FILE = os.getenv("LIVE_PHASE_FILE") or os.path.join(BASE_DIR, "phase.json")


def _read_phase_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


_PHASE = _read_phase_file(PHASE_FILE)


def _phase_setting(env_key, file_key, default=""):
    env_value = os.getenv(env_key)
    if env_value is not None and str(env_value).strip() != "":
        return str(env_value).strip()
    value = _PHASE.get(file_key)
    if value is None:
        return default
    return value


_stats_start_raw = str(_phase_setting("LIVE_STATS_START", "stats_start", "2026-09-16T00:00:00") or "").strip()
STATS_START = "" if _stats_start_raw.lower() in ("off", "none", "false", "0", "no") else _stats_start_raw
INCLUDE_HISTORY_BASELINE = str(
    _phase_setting("LIVE_INCLUDE_HISTORY", "include_history", "0")
).strip().lower() in ("1", "true", "yes", "y", "是", "on")
PHASE_LABEL = str(_PHASE.get("label") or "预热阶段").strip() or "预热阶段"

# 模拟采集器只用于链路演示。正式大屏默认关闭，避免混入实时统计。
SIM_ENABLED = os.getenv("LIVE_SIM_ENABLED", "0") == "1"
SIM_INTERVAL = int(os.getenv("LIVE_SIM_INTERVAL", "12"))
SIM_BATCH_MIN = int(os.getenv("LIVE_SIM_BATCH_MIN", "1"))
SIM_BATCH_MAX = int(os.getenv("LIVE_SIM_BATCH_MAX", "3"))

# 文件导入（人工导出/每日更新的渠道，把 json/csv 丢进 inbox/ 即可）
FILE_WATCH_ENABLED = os.getenv("LIVE_FILE_WATCH_ENABLED", "1") == "1"
FILE_WATCH_INTERVAL = int(os.getenv("LIVE_FILE_WATCH_INTERVAL", "10"))

# 真实渠道采集配置（B站 / Reddit）
SEARCH_KEYWORDS = [
    k.strip() for k in os.getenv(
        "LIVE_SEARCH_KEYWORDS",
        "2026年民族团结进步宣传周,首个民族团结进步宣传周,民族团结进步宣传周主场活动,民族团结进步宣传周",
    ).split(",") if k.strip()
]
MAX_RESULTS = int(os.getenv("LIVE_MAX_RESULTS", "10"))
REQUEST_INTERVAL = float(os.getenv("LIVE_REQUEST_INTERVAL", "2"))
HTTP_TIMEOUT = int(os.getenv("LIVE_HTTP_TIMEOUT", "15"))

# B站：是否补充点赞/评论/转发（每个视频多一次请求）
BILIBILI_ENRICH_STATS = os.getenv("LIVE_BILIBILI_ENRICH", "1") == "1"

# Reddit：配置密钥后走官方 OAuth；未配置则使用公开 JSON 搜索（限速）
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "").strip()
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "yuqing-monitor/1.0 (local demo)")

# 微博：热榜（公开接口，无需登录）+ 第三方导出文件；开放平台 API / 移动端 Cookie 可选
# WEIBO_MODE: auto（热榜+导出，配了密钥/Cookie 自动叠加）| hot | export | openapi | mobile
WEIBO_MODE = os.getenv("WEIBO_MODE", "auto").strip().lower()
WEIBO_EXPORT_DIR = os.getenv("WEIBO_EXPORT_DIR", os.path.join(BASE_DIR, "data", "weibo_exports"))
WEIBO_HOT_KEYWORDS = [
    k.strip() for k in os.getenv(
        "WEIBO_HOT_KEYWORDS",
        "民族团结进步宣传周,宣传周,民族团结,少数民族,民族地区,歧视",
    ).split(",") if k.strip()
]
WEIBO_HOT_COUNTED = os.getenv("WEIBO_HOT_COUNTED", "是").strip()
WEIBO_HOT_AS_LIKES = os.getenv("WEIBO_HOT_AS_LIKES", "1") == "1"
# 开放平台（需开发者资质；搜索接口一般要高级权限）
WEIBO_APP_KEY = os.getenv("WEIBO_APP_KEY", "").strip()
WEIBO_APP_SECRET = os.getenv("WEIBO_APP_SECRET", "").strip()
WEIBO_ACCESS_TOKEN = os.getenv("WEIBO_ACCESS_TOKEN", "").strip()
# 移动端搜索（实验通道）：浏览器登录 m.weibo.cn 后复制 Cookie 填这里，有风控/封号风险
WEIBO_COOKIE = os.getenv("WEIBO_COOKIE", "").strip()

# 抖音：热榜公开接口（无需登录，实测可用）；关键词搜索需登录，暂未接入
DOUYIN_HOT_KEYWORDS = [
    k.strip() for k in os.getenv(
        "DOUYIN_HOT_KEYWORDS",
        "民族团结进步宣传周,宣传周,民族团结,少数民族,民族地区,歧视",
    ).split(",") if k.strip()
]
DOUYIN_HOT_COUNTED = os.getenv("DOUYIN_HOT_COUNTED", "是").strip()
DOUYIN_HOT_AS_LIKES = os.getenv("DOUYIN_HOT_AS_LIKES", "1") == "1"

# 微信公众号：搜狗微信文章搜索（无需登录；反爬验证码风险，频率放低）
WECHAT_SOGOU_PAGES = int(os.getenv("WECHAT_SOGOU_PAGES", "1"))
WECHAT_SOGOU_INTERVAL = float(os.getenv("WECHAT_SOGOU_INTERVAL", "5"))

# 百度知道：搜索公开页（无需登录；验证码风控，频率放低）
BAIDU_ZHIDAO_PAGES = int(os.getenv("BAIDU_ZHIDAO_PAGES", "1"))
BAIDU_ZHIDAO_INTERVAL = float(os.getenv("BAIDU_ZHIDAO_INTERVAL", "5"))

# 豆瓣：小组讨论搜索公开页（无需登录；频率放低）
DOUBAN_GROUP_PAGES = int(os.getenv("DOUBAN_GROUP_PAGES", "1"))
DOUBAN_GROUP_INTERVAL = float(os.getenv("DOUBAN_GROUP_INTERVAL", "5"))

# 省市政务/媒体网站：通用 HTML 标题级采集（site_sources.json 驱动）
SITE_NEWS_ENABLED = os.getenv("LIVE_SITE_NEWS_ENABLED", "1") == "1"
SITE_NEWS_INTERVAL = int(os.getenv("LIVE_SITE_NEWS_INTERVAL", "1800"))
SITE_NEWS_MAX_SITES = int(os.getenv("LIVE_SITE_NEWS_MAX_SITES", "15"))
SITE_NEWS_MAX_ITEMS = int(os.getenv("LIVE_SITE_NEWS_MAX_ITEMS", "10"))
# 逗号分隔的省份/站点名/类别过滤，例如 LIVE_SITE_NEWS_SOURCES=河北,山西
SITE_NEWS_SOURCES = os.getenv("LIVE_SITE_NEWS_SOURCES", "").strip()
SITE_NEWS_SOURCES_JSON = os.getenv(
    "LIVE_SITE_NEWS_SOURCES_JSON",
    os.path.join(BASE_DIR, "site_sources.json"),
)

# SSE 心跳间隔（秒）
HEARTBEAT_INTERVAL = int(os.getenv("LIVE_HEARTBEAT_INTERVAL", "15"))

# 实时服务端：是否自动调度真实平台采集器（微博/抖音/B站/公众号/百度知道/豆瓣）
# 开启后采集到的新数据立即走 SSE 推送；各采集器仍按自身 interval 轮询。
LIVE_PLATFORM_ENABLED = os.getenv("LIVE_PLATFORM_ENABLED", "0") == "1"
LIVE_PLATFORM_POLL = int(os.getenv("LIVE_PLATFORM_POLL", "10"))

# 历史基线来自此前采集入库链路，用于累计量；正式大屏默认迁入数据库展示。
LIVE_MIGRATE_HISTORY = os.getenv("LIVE_MIGRATE_HISTORY", "1") == "1"

PLATFORM_GROUPS = [
    "微博/热榜",
    "抖音等视频平台",
    "快手",
    "小红书/豆瓣等平台",
    "知乎/B站/百度知道",
    "贴吧/头条/新闻评论",
    "微信公众号/视频号",
    "省市政务/媒体网站",
    "其他",
]
