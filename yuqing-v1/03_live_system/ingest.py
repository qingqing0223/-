# -*- coding: utf-8 -*-
"""字段统一规范 + 归一化 + 入库"""
import hashlib
import re
from datetime import datetime

import db
from classify import classify


def _clean(v):
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v).replace("\u3000", " ").replace("\xa0", " ")).strip()


def _to_int(v):
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    s = _clean(v).replace(",", "").replace("，", "")
    m = re.search(r"([\d.]+)\s*(万|w|W|k|K)?", s)
    if not m:
        return 0
    val = float(m.group(1))
    unit = m.group(2)
    if unit and unit.lower() == "万":
        val *= 10000
    elif unit and unit.lower() == "k":
        val *= 1000
    return int(val)


def _to_dt(v):
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%dT%H:%M:%S")
    s = _clean(v)
    if not s:
        return ""
    m = re.search(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})(?:[ T日](\d{1,2})[:：点时](\d{1,2})?(?:[:：分](\d{1,2}))?)?", s)
    if not m:
        return ""
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hh = int(m.group(4) or 0)
    mm = int(m.group(5) or 0)
    ss = int(m.group(6) or 0)
    try:
        return datetime(y, mo, d, hh, mm, ss).strftime("%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return ""


def _first(rec, names):
    for n in names:
        if n in rec and rec[n] is not None and _clean(rec[n]):
            return rec[n]
    return ""


def platform_group(name):
    s = _clean(name)
    rules = [
        ("微博/热榜", ["微博", "热榜"]),
        ("抖音等视频平台", ["抖音", "火山", "视频平台"]),
        ("快手", ["快手"]),
        ("小红书/豆瓣等平台", ["小红书", "豆瓣"]),
        ("知乎/B站/百度知道", ["知乎", "哔哩哔哩", "B站", "bilibili", "百度知道"]),
        ("省市政务/媒体网站", ["政务网站", "新闻网站", "政府网站", "省市政务"]),
        ("贴吧/头条/新闻评论", ["贴吧", "头条", "新闻"]),
        ("微信公众号/视频号", ["微信", "公众号", "视频号"]),
    ]
    for group, keys in rules:
        if any(k in s for k in keys):
            return group
    return "其他"


def attitude_bucket(attitude):
    s = _clean(attitude)
    # 否决口径必须先判：「非支持/非肯定」同时含「非支持」和「肯定」，
    # 若先匹配正向词会被错误归入 support，导致大屏支持率虚高。
    if any(k in s for k in ("非支持", "非肯定", "批评", "投诉", "担忧", "咨询", "公平", "歧视", "实施", "维权", "质疑", "不了解")):
        return "non_support"
    if any(k in s for k in ("支持", "认可", "赞同", "肯定")):
        return "support"
    if any(k in s for k in ("中性", "观点不明")):
        return "neutral"
    if "建议" in s:
        return "suggest"
    return "other"


def issue_category(attitude):
    s = _clean(attitude)
    mapping = [
        ("咨询疑问", ["咨询", "疑问", "诉求"]),
        ("担忧影响", ["担忧", "影响", "担心"]),
        ("明确批评", ["批评", "质疑"]),
        ("投诉维权", ["投诉", "维权", "举报"]),
        ("实施问题", ["实施"]),
        ("公平争议", ["公平"]),
        ("歧视偏见", ["歧视"]),
        ("不了解该法律", ["不了解"]),
    ]
    for name, keys in mapping:
        if any(k in s for k in keys):
            return name
    return ""


MINORITY_LANGS = ["维吾尔", "彝", "藏", "哈萨克", "蒙古", "蒙", "回", "苗", "壮", "朝鲜", "满", "傣", "白族", "纳西", "景颇", "瑶", "侗", "土家"]


def is_minority_lang(lang):
    s = _clean(lang)
    if not s:
        return 0
    if any(k in s for k in ("中文", "普通话", "汉语", "英语", "英文")):
        return 0
    return 1 if any(k in s for k in MINORITY_LANGS) else 0


FIELD_ALIASES = {
    "uid": ["唯一编号", "uid", "id", "编号"],
    "collected_at": ["采集时间", "采集日期", "collected_at", "抓取时间"],
    "published_at": ["发布时间", "发布日期", "评论日期", "日期", "published_at", "发布时间/采集日期"],
    "platform": ["平台", "平台/网站", "平台或网站", "平台或网站/网站", "platform"],
    "source": ["具体来源", "来源", "来源账号/栏目", "来源网站", "source"],
    "account": ["账号", "账号名称", "账号或栏目名称", "账号名称/发布单位", "昵称", "发布者", "account"],
    "text": ["正文", "评论原文", "原文证据摘录", "原话", "原话/代表性原话", "评论观点", "中文译文", "内容", "text"],
    "url": ["原始链接", "链接", "来源链接", "url"],
    "region": ["地区", "涉及地区", "统计地区", "评论者公开地区", "地区大类", "region"],
    "province": ["省份", "省", "province"],
    "city": ["城市", "city"],
    "ip_location": ["IP属地", "ip_location", "IP"],
    "language": ["语言", "原始语言", "language"],
    "attitude": ["总体态度", "态度", "态度类别", "意见类型", "attitude"],
    "issue_category": ["具体问题类别", "问题类别", "issue_category"],
    "likes": ["点赞量", "点赞", "likes"],
    "comments": ["评论量", "评论数", "评论", "comments"],
    "shares": ["转发量", "转发", "shares"],
    "is_key": ["是否为重点舆情", "重点舆情", "是否重点", "is_key"],
    "notes": ["其他备注", "备注", "说明", "notes"],
}


def normalize_record(raw):
    raw = raw or {}
    rec = {}
    for field, aliases in FIELD_ALIASES.items():
        rec[field] = _first(raw, aliases)
    rec["platform"] = _clean(rec["platform"])
    rec["text"] = _clean(rec["text"])
    rec["collected_at"] = _to_dt(rec["collected_at"]) or datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    rec["published_at"] = _to_dt(rec["published_at"])
    rec["platform_group"] = platform_group(rec["platform"])
    rec["attitude"] = _clean(rec["attitude"]) or "待核实"
    rec["attitude_bucket"] = attitude_bucket(rec["attitude"])
    rec["issue_category"] = _clean(rec["issue_category"]) or issue_category(rec["attitude"])
    rec["language"] = _clean(rec["language"]) or "中文"
    rec["is_minority"] = is_minority_lang(rec["language"])
    rec["likes"] = _to_int(rec["likes"])
    rec["comments"] = _to_int(rec["comments"])
    rec["shares"] = _to_int(rec["shares"])
    rec["is_key"] = 1 if _clean(rec["is_key"]) in ("1", "是", "Y", "y", "true", "True") else 0
    rec["region"] = _clean(rec["region"])
    rec["province"] = _clean(rec["province"])
    rec["city"] = _clean(rec["city"])
    rec["ip_location"] = _clean(rec["ip_location"])
    rec["source"] = _clean(rec["source"])
    rec["account"] = _clean(rec["account"])
    rec["url"] = _clean(rec["url"])
    rec["notes"] = _clean(rec["notes"])
    rec["origin"] = _clean(raw.get("origin")) or "api"
    if not rec["uid"]:
        key = "|".join([rec["platform"], rec["published_at"], rec["account"], rec["text"]])
        rec["uid"] = rec["origin"] + "-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return rec


def classify_and_prepare(rec, force_accept=False):
    if force_accept:
        # 重点账号（creator）数据是按账号清单定向采集的，不再做关键词相关性过滤
        rec["is_relevant"] = 1
        rec["status"] = "accepted"
        return rec
    relevant, reason = classify(rec["text"], rec["platform"])
    rec["is_relevant"] = 1 if relevant else 0
    rec["status"] = "accepted" if relevant else "pending"
    if not relevant:
        rec["notes"] = (rec["notes"] + " | " if rec["notes"] else "") + reason
    return rec


def ingest_records(records, origin="api", force_accept=False):
    """入库一批记录，返回 (已入库列表, 去重跳过数)"""
    inserted = []
    skipped = 0
    for raw in records:
        rec = normalize_record(raw)
        rec["origin"] = _clean(raw.get("origin")) or origin
        classify_and_prepare(rec, force_accept=force_accept)
        row = db.insert_incident(rec)
        if row:
            inserted.append(row)
        else:
            skipped += 1
    return inserted, skipped
