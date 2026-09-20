# -*- coding: utf-8 -*-
"""统计引擎：预热阶段只统计“实际入库”的数据（可与第一阶段历史基线隔离）。

统计口径见 03_live_system/phase.json（环境变量可覆盖）：

* ``stats_start``：只统计该时间点之后入库（collected_at）的记录；
  设为 off/空 表示不做时间过滤。
* ``include_history``：=1 时恢复“第一阶段 data.js 基线 + 实时增量”的旧口径；
  默认 0，即大屏只显示统计起点之后实际入库的数据，旧主题历史记录保留在库中但不参与展示。

顶部 KPI、平台、地区、小时趋势、重点账号全部取自同一批入库记录，
因此与采集端（--main）实际入库数量一致。
"""
from __future__ import annotations

import copy
import json
import os
import re
from datetime import datetime, timedelta

import db
from config import BASE_DATA_JS, INCLUDE_HISTORY_BASELINE, PHASE_LABEL, STATS_START

HOUR_LOOKBACK_LIMIT = 24 * 15
QUOTE_LIMIT = 1500
KEY_ACCOUNT_LIMIT = 30
EXCLUDED_LIVE_ORIGINS = ("simulator", "demo")
RISK_LIMIT = 80
OLD_LAW_TERMS = ("民族团结进步促进法", "促进法")

# 固定关注的 10 个重点地区：五个自治区 + 北京、上海、广州、武汉、哈尔滨
# 省/自治区按省级字段匹配；广州/武汉/哈尔滨是城市，同时接受地区文本命中。
FOCUS_REGIONS = [
    {"name": "新疆", "full": "新疆维吾尔自治区", "provinces": ["新疆"], "keywords": ["新疆", "乌鲁木齐"]},
    {"name": "西藏", "full": "西藏自治区", "provinces": ["西藏"], "keywords": ["西藏", "拉萨"]},
    {"name": "内蒙古", "full": "内蒙古自治区", "provinces": ["内蒙古"], "keywords": ["内蒙古", "呼和浩特"]},
    {"name": "广西", "full": "广西壮族自治区", "provinces": ["广西"], "keywords": ["广西", "南宁"]},
    {"name": "宁夏", "full": "宁夏回族自治区", "provinces": ["宁夏"], "keywords": ["宁夏", "银川"]},
    {"name": "北京", "full": "北京市", "provinces": ["北京"], "keywords": ["北京"]},
    {"name": "上海", "full": "上海市", "provinces": ["上海"], "keywords": ["上海"]},
    {"name": "广州", "full": "广东省广州市", "provinces": ["广东"], "keywords": ["广州"]},
    {"name": "武汉", "full": "湖北省武汉市", "provinces": ["湖北"], "keywords": ["武汉"]},
    {"name": "哈尔滨", "full": "黑龙江省哈尔滨市", "provinces": ["黑龙江"], "keywords": ["哈尔滨"]},
]

# 右上角单独展示的 9 个平台：不做任何平台组合并
PLATFORM_ORDER = ["小红书", "抖音", "快手", "B站", "微博", "今日头条", "知乎", "微信公众号", "视频号"]
# 匹配顺序很重要：「微信视频号」必须先命中「视频号」，不能落到「微信公众号」
PLATFORM_MATCH_ORDER = ["视频号", "微信公众号", "小红书", "抖音", "快手", "B站", "微博", "今日头条", "知乎"]
PLATFORM_ALIASES = {
    "小红书": ["小红书", "xhs", "redbook", "红书"],
    "抖音": ["抖音", "douyin"],
    "快手": ["快手", "kuaishou"],
    "B站": ["b站", "bilibili", "哔哩哔哩", "哔哩", "弹幕"],
    "微博": ["微博", "weibo", "热榜"],
    "今日头条": ["今日头条", "toutiao", "头条"],
    "知乎": ["知乎", "zhihu"],
    "微信公众号": ["微信公众号", "公众号", "微信公众平台", "微信", "wechat", "mp"],
    "视频号": ["视频号", "channels"],
}

# 重点账号（creator 监测）来源标记：is_key=1 或 origin 命中其一即纳入重点账号模块
KEY_ACCOUNT_ORIGINS = ("creator", "creator_monitor", "key_account", "key_accounts", "keyaccount", "key-account")


def parse_data_js(path):
    with open(path, encoding="utf-8") as f:
        s = f.read()
    s = re.sub(r"^.*?window\.DASH_DATA\s*=\s*", "", s, count=1, flags=re.S)
    s = s.strip().rstrip(";").strip()
    return json.loads(s)


def load_base_data():
    source_mtime = str(os.path.getmtime(BASE_DATA_JS))
    data = db.get_meta("base_data")
    cached_mtime = db.get_meta("base_data_mtime")
    if data is None or cached_mtime != source_mtime:
        data = parse_data_js(BASE_DATA_JS)
        db.set_meta("base_data", data)
        db.set_meta("base_data_mtime", source_mtime)
    return data


def now_iso():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _add_num(d, key, n):
    d[key] = d.get(key, 0) + n


def _int(value):
    try:
        return int(float(value or 0))
    except Exception:
        return 0


def _norm_ts(value):
    return str(value or "").strip()[:19]


def _hour_key(value):
    return _norm_ts(value)[:13]


def _day_key(value):
    return _norm_ts(value)[:10]


def canonical_platform(name):
    """把各平台的不同写法归一到 9 个展示平台之一；未识别的返回“其他”。"""
    text = str(name or "").strip()
    if not text:
        return ""
    low = text.lower()
    for canon in PLATFORM_MATCH_ORDER:
        if any(alias in low for alias in PLATFORM_ALIASES[canon]):
            return canon
    return "其他"


def _platform_bucket(name):
    return {
        "name": name, "total": 0, "support": 0, "neutral": 0, "nonSupport": 0,
        "hour": 0,
        "qa": 0, "worry": 0, "criticism": 0, "complaint": 0, "implement": 0,
        "fairness": 0, "discrimination": 0, "suggest": 0, "other": 0,
        "likes": 0, "comments": 0, "shares": 0, "share": 0.0, "supportRate": 0.0,
    }


def _focus_bucket(spec):
    return {
        "name": spec["name"], "full": spec["full"], "provinces": list(spec["provinces"]),
        "total": 0, "hour": 0, "support": 0, "neutral": 0, "nonSupport": 0,
        "qa": 0, "worry": 0, "criticism": 0, "complaint": 0, "implement": 0,
        "fairness": 0, "discrimination": 0, "other": 0,
        "platforms": {}, "topPlatform": "", "latest": "",
    }


def _category_key(category):
    return {
        "咨询疑问": "qa", "担忧影响": "worry", "明确批评": "criticism", "投诉维权": "complaint",
        "实施问题": "implement", "公平争议": "fairness", "歧视偏见": "discrimination",
    }.get(category)


def _is_risk_row(row, bucket, category):
    if bucket == "non_support":
        return True
    text = " ".join(str(row.get(k) or "") for k in ("text", "attitude", "issue_category", "notes"))
    return any(k in text for k in ("风险", "质疑", "担忧", "投诉", "维权", "歧视", "偏见", "批评", "负面", "舆情"))


def _focus_names(row):
    hay = " ".join(str(row.get(k) or "") for k in ("province", "city", "region", "ip_location"))
    if not hay.strip():
        return []
    return [spec["name"] for spec in FOCUS_REGIONS if any(k in hay for k in spec["keywords"])]


def _empty_base():
    """预热阶段口径下的空基线：保留结构，不带任何历史数据。"""
    return {
        "topStats": {},
        "platforms": [],
        "regions": [],
        "provinces": [],
        "languagePlatform": [],
        "trend": [],
        "quotes": [],
        "hotTop": [],
        "attitude": {
            "macro": [
                {"name": "支持认可", "value": 0},
                {"name": "中性信息", "value": 0},
                {"name": "参与建议", "value": 0},
                {"name": "问题", "value": 0},
            ],
            "detail": [
                {"name": name, "value": 0}
                for name in (
                    "支持认可", "中性信息", "咨询疑问", "担忧影响", "明确批评",
                    "投诉维权", "实施问题", "公平争议", "歧视偏见", "参与建议", "不了解该法律",
                )
            ],
        },
        "nonSupport": [],
    }


def compute_live_stats():
    placeholders = ",".join("?" for _ in EXCLUDED_LIVE_ORIGINS)
    sql = f"SELECT * FROM incidents WHERE status='accepted' AND COALESCE(origin,'') NOT IN ({placeholders})"
    params = list(EXCLUDED_LIVE_ORIGINS)
    if STATS_START:
        sql += " AND collected_at>=?"
        params.append(STATS_START)
    for term in OLD_LAW_TERMS:
        sql += (
            " AND COALESCE(text,'') NOT LIKE ?"
            " AND COALESCE(notes,'') NOT LIKE ?"
            " AND COALESCE(source,'') NOT LIKE ?"
        )
        params.extend([f"%{term}%", f"%{term}%", f"%{term}%"])
    sql += " ORDER BY id DESC"
    rows = db.query_all(sql, params)

    now = datetime.now()
    recent_cut = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S")
    hour_cut = now.strftime("%Y-%m-%dT%H:00:00")

    acc = {
        "total": 0, "support": 0, "neutral": 0, "suggest": 0,
        "non_support": 0, "other": 0, "region_total": 0, "region_support": 0,
        "minority": 0, "recent10m": 0, "current_hour": 0,
        "region_count": 0, "platform_count": 0, "platform_count_all": len(PLATFORM_ORDER),
    }
    platforms = {}
    platform_details = {}
    unknown_platforms = {}
    regions = {}
    provinces = {}
    langs = {}
    trend = {}
    hourly = {}
    nonsup = {}
    hot = []
    risks = []
    focus = {spec["name"]: _focus_bucket(spec) for spec in FOCUS_REGIONS}
    key_accounts = {}
    region_names = set()

    for r in rows:
        ts = _norm_ts(r["collected_at"])
        bucket = r["attitude_bucket"] or "other"
        category = r["issue_category"] or ""
        cat_key = _category_key(category)
        likes = _int(r["likes"])
        comments = _int(r["comments"])
        shares = _int(r["shares"])
        is_risk = _is_risk_row(r, bucket, category)

        acc["total"] += 1
        _add_num(acc, bucket, 1)
        if ts and ts >= recent_cut:
            acc["recent10m"] += 1
        if ts and ts >= hour_cut:
            acc["current_hour"] += 1
        if r["region"]:
            acc["region_total"] += 1
            if bucket == "support":
                acc["region_support"] += 1
        if r["is_minority"]:
            acc["minority"] += 1

        # 平台组（兼容旧字段）
        group = r["platform_group"] or "其他"
        pg = platforms.setdefault(group, {
            "name": group, "total": 0, "support": 0, "neutral": 0, "qa": 0, "worry": 0,
            "criticism": 0, "complaint": 0, "implement": 0, "fairness": 0,
            "discrimination": 0, "suggest": 0, "unknownLaw": 0, "other": 0,
            "supportRate": 0.0, "nonSupport": 0,
        })
        pg["total"] += 1
        pg["support"] += 1 if bucket == "support" else 0
        pg["neutral"] += 1 if bucket == "neutral" else 0
        pg["suggest"] += 1 if bucket == "suggest" else 0
        if bucket == "non_support":
            pg["nonSupport"] += 1
            if cat_key:
                pg[cat_key] += 1
            else:
                pg["other"] += 1
            _add_num(nonsup, category or "其他/未分类", 1)

        # 9 个平台各自独立统计（不做任何合并）
        canon = canonical_platform(r["platform"])
        if canon:
            pd = platform_details.setdefault(canon, _platform_bucket(canon))
            pd["total"] += 1
            if ts and ts >= hour_cut:
                pd["hour"] += 1
            pd["support"] += 1 if bucket == "support" else 0
            pd["neutral"] += 1 if bucket == "neutral" else 0
            pd["suggest"] += 1 if bucket == "suggest" else 0
            if bucket == "non_support":
                pd["nonSupport"] += 1
                if cat_key:
                    pd[cat_key] += 1
            pd["likes"] += likes
            pd["comments"] += comments
            pd["shares"] += shares
            if canon == "其他":
                pname = str(r["platform"] or "未标注")
                unknown_platforms[pname] = unknown_platforms.get(pname, 0) + 1

        # 地区（地区组）
        if r["province"] or r["region"]:
            name = r["province"] or r["region"] or "未分组"
            reg = regions.setdefault(name, {
                "name": name, "total": 0, "support": 0, "neutral": 0, "qa": 0, "worry": 0,
                "criticism": 0, "complaint": 0, "implement": 0, "fairness": 0,
                "discrimination": 0, "pending": 0, "provinces": [name],
                "sourceGroup": r["region"] or "",
            })
            reg["total"] += 1
            reg["support"] += 1 if bucket == "support" else 0
            reg["neutral"] += 1 if bucket == "neutral" else 0
            if cat_key:
                reg[cat_key] += 1
            region_names.add(str(name).strip())

        # 省级（地图）
        if r["province"]:
            name = r["province"]
            prov = provinces.setdefault(name, {
                "name": name, "short": name, "value": 0, "total": 0, "support": 0,
                "neutral": 0, "qa": 0, "worry": 0, "criticism": 0, "complaint": 0,
                "implement": 0, "fairness": 0, "discrimination": 0, "suggest": 0, "other": 0,
            })
            prov["value"] += 1
            prov["total"] += 1
            prov["support"] += 1 if bucket == "support" else 0
            prov["neutral"] += 1 if bucket == "neutral" else 0
            if cat_key:
                prov[cat_key] += 1
            elif bucket == "suggest":
                prov["suggest"] += 1
            else:
                prov["other"] += 1
            region_names.add(str(name).strip())

        # 固定关注的 10 个重点地区
        for focus_name in _focus_names(r):
            fr = focus[focus_name]
            fr["total"] += 1
            if ts and ts >= hour_cut:
                fr["hour"] += 1
            fr["support"] += 1 if bucket == "support" else 0
            fr["neutral"] += 1 if bucket == "neutral" else 0
            if bucket == "non_support":
                fr["nonSupport"] += 1
                if cat_key:
                    fr[cat_key] += 1
                else:
                    fr["other"] += 1
            if canon:
                fr["platforms"][canon] = fr["platforms"].get(canon, 0) + 1
            if ts and ts > fr["latest"]:
                fr["latest"] = ts

        # 语言
        lang = r["language"] or "中文"
        lv = langs.get(lang, {"name": lang, "value": 0})
        lv["value"] += 1
        langs[lang] = lv

        # 趋势：按天 + 按小时（按入库时间）
        day = _day_key(ts)
        if day:
            trend[day] = trend.get(day, 0) + 1
        hk = _hour_key(ts)
        if hk:
            hb = hourly.setdefault(hk, {"hour": hk, "value": 0, "heat": 0})
            hb["value"] += 1
            hb["heat"] += likes + comments + shares

        # 高热内容
        if likes:
            hot.append({
                "platform": canon or r["platform"] or r["platform_group"] or "",
                "account": r["account"] or "",
                "title": (r["text"] or "")[:60],
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "date": day,
            })

        if is_risk:
            risks.append(r)

        # 重点账号 / 大V 传播监测（is_key=1，或由 creator 监测接口写入）
        origin = str(r["origin"] or "").strip().lower()
        if r["is_key"] or origin in KEY_ACCOUNT_ORIGINS:
            account = str(r["account"] or "").strip()
            if account:
                pkey = canon or str(r["platform"] or "").strip() or "未标注平台"
                item = key_accounts.setdefault((account, pkey), {
                    "account": account, "platform": pkey,
                    "posts": 0, "likes": 0, "comments": 0, "shares": 0,
                    "heat": 0, "support": 0, "nonSupport": 0,
                    "latestAt": "", "latestText": "", "url": "",
                    "source": origin or "live",
                })
                item["posts"] += 1
                item["likes"] += likes
                item["comments"] += comments
                item["shares"] += shares
                item["heat"] = item["likes"] + item["comments"] + item["shares"]
                if bucket == "support":
                    item["support"] += 1
                elif bucket == "non_support":
                    item["nonSupport"] += 1
                if ts >= item["latestAt"]:
                    item["latestAt"] = ts
                    item["latestText"] = (r["text"] or "")[:80]
                    item["url"] = r["url"] or item["url"]

    # 平台行：固定 9 个平台、固定顺序，未出现的平台补 0
    platform_rows = []
    for name in PLATFORM_ORDER:
        platform_rows.append(platform_details.get(name, _platform_bucket(name)))
    total_platform = sum(row["total"] for row in platform_rows)
    for row in platform_rows:
        row["share"] = round(row["total"] / total_platform * 100, 2) if total_platform else 0.0
        row["supportRate"] = round(row["support"] / row["total"] * 100, 2) if row["total"] else 0.0

    for fr in focus.values():
        top = sorted(fr["platforms"].items(), key=lambda kv: kv[1], reverse=True)
        fr["topPlatform"] = top[0][0] if top else ""

    hot.sort(key=lambda x: x["likes"], reverse=True)
    risks.sort(key=lambda x: str(x.get("collected_at") or ""), reverse=True)
    key_rows = sorted(
        key_accounts.values(),
        key=lambda x: (x["posts"], x["heat"], x["likes"]),
        reverse=True,
    )[:KEY_ACCOUNT_LIMIT]

    acc["region_count"] = len({n for n in region_names if n})
    acc["platform_count"] = sum(1 for row in platform_rows if row["total"] > 0)
    acc["platform_count_all"] = len(PLATFORM_ORDER)

    return {
        "counts": acc,
        "platforms": list(platforms.values()),
        "platform_rows": platform_rows,
        "unknown_platforms": [
            {"name": k, "value": v}
            for k, v in sorted(unknown_platforms.items(), key=lambda kv: kv[1], reverse=True)[:10]
        ],
        "regions": list(regions.values()),
        "provinces": list(provinces.values()),
        "focus": [focus[spec["name"]] for spec in FOCUS_REGIONS],
        "key_accounts": key_rows,
        "languages": list(langs.values()),
        "trend_daily": trend,
        "trend_hourly": hourly,
        "hourly_rows": build_hourly_rows(hourly),
        "nonSupport": nonsup,
        "hot": hot,
        "risks": risks[:RISK_LIMIT],
        "pending": db.query_one("SELECT COUNT(*) AS n FROM incidents WHERE status='pending'")["n"],
        "rows": rows,
    }


def build_hourly_rows(hourly):
    """从统计起点当天 00:00 到当前小时，补齐连续小时桶（新增数 + 传播热度）。"""
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    start_dt = now - timedelta(hours=23)
    if STATS_START:
        try:
            start_dt = datetime.strptime(_norm_ts(STATS_START)[:13], "%Y-%m-%dT%H")
        except Exception:
            start_dt = now - timedelta(hours=23)
    if start_dt > now:
        start_dt = now
    if (now - start_dt).total_seconds() / 3600 > HOUR_LOOKBACK_LIMIT:
        start_dt = now - timedelta(hours=HOUR_LOOKBACK_LIMIT)
    out = []
    cur = start_dt
    while cur <= now:
        key = cur.strftime("%Y-%m-%dT%H")
        row = hourly.get(key) or {"value": 0, "heat": 0}
        out.append({
            "hour": key,
            "label": cur.strftime("%H:00"),
            "date": cur.strftime("%Y-%m-%d"),
            "value": row["value"],
            "heat": row["heat"],
        })
        cur += timedelta(hours=1)
    return out


def row_to_quote(r):
    return {
        "platform": r["platform"] or r["platform_group"] or "",
        "platformGroup": r.get("platform_group") or "",
        "region": r["region"] or r["province"] or "",
        "province": r.get("province") or "",
        "city": r.get("city") or "",
        "group": r["region"] or "",
        "attitude": r["attitude"] or "",
        "attitudeBucket": r.get("attitude_bucket") or "",
        "issueCategory": r.get("issue_category") or "",
        "text": r["text"] or "",
        "date": (r["published_at"] or "")[:10],
        "hour": _hour_key(r.get("collected_at")),
        "source": r["source"] or r["origin"] or "",
        "src": r["source"] or r["origin"] or "",
        "account": r["account"] or "",
        "language": r["language"] or "中文",
        "collectedAt": r["collected_at"] or "",
        "isLive": True,
        "id": r["id"],
    }


def merge_into_list(base_list, extra_list, key, sum_keys):
    out = copy.deepcopy(base_list)
    by = {}
    for item in out:
        by[item.get(key, "")] = item
    for extra in extra_list:
        name = extra.get(key, "")
        if not name:
            continue
        if name in by:
            for k in sum_keys:
                by[name][k] = (by[name].get(k, 0) or 0) + (extra.get(k, 0) or 0)
        else:
            item = copy.deepcopy(extra)
            item.setdefault("total", 0)
            by[name] = item
    return list(by.values())


def normalize_trend(trend_by, start="2026-07-01"):
    """Return a continuous daily timeline from the given start date."""
    cleaned = {}
    for d, v in trend_by.items():
        if not d or d < start:
            continue
        cleaned[d] = cleaned.get(d, 0) + (v or 0)
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_key = max(cleaned.keys(), default=now_iso()[:10])
    end_dt = max(datetime.strptime(end_key, "%Y-%m-%d"), start_dt)
    rows = []
    cur = start_dt
    while cur <= end_dt:
        key = cur.strftime("%Y-%m-%d")
        rows.append({"date": key, "value": cleaned.get(key, 0)})
        cur += timedelta(days=1)
    return rows


def build_bootstrap():
    phase_only = bool(STATS_START) and not INCLUDE_HISTORY_BASELINE
    base = _empty_base() if phase_only else copy.deepcopy(load_base_data())
    live = compute_live_stats()
    c = live["counts"]

    # 顶部实时指标：全部来自实际入库记录
    ts = base.setdefault("topStats", {})
    ts["totalOpinions"] = (ts.get("totalOpinions") or 0) + c["total"]
    ts["totalOpinionsLabel"] = ts.get("totalOpinionsLabel") or "累计信息数"
    ts["supportCount"] = (ts.get("supportCount") or 0) + c["support"]
    ts["regionOpinions"] = (ts.get("regionOpinions") or 0) + c["region_total"]
    ts["regionSupport"] = (ts.get("regionSupport") or 0) + c["region_support"]
    ts["nonSupport"] = (ts.get("nonSupport") or 0) + c["non_support"]
    ts["minorityLang"] = (ts.get("minorityLang") or 0) + c["minority"]
    ts["recent10m"] = c["recent10m"]
    ts["currentHour"] = c["current_hour"]
    ts["detectedRegionCount"] = c["region_count"]
    ts["detectedPlatformCount"] = c["platform_count"]
    ts["detectedPlatformCountAll"] = c["platform_count_all"]
    ts["supportRate"] = round((ts.get("supportCount") or 0) / ts["totalOpinions"] * 100, 2) if ts.get("totalOpinions") else 0.0
    ts["regionSupportRate"] = round((ts.get("regionSupport") or 0) / ts["regionOpinions"] * 100, 2) if ts.get("regionOpinions") else 0.0

    # 平台组 / 地区 / 省级 / 语言
    base["platforms"] = merge_into_list(
        base.get("platforms", []), live["platforms"], "name",
        ["total", "support", "neutral", "qa", "worry", "criticism", "complaint",
         "implement", "fairness", "discrimination", "suggest", "unknownLaw", "other", "nonSupport"],
    )
    base["regions"] = merge_into_list(
        base.get("regions", []), live["regions"], "name",
        ["total", "support", "neutral", "qa", "worry", "criticism", "complaint",
         "implement", "fairness", "discrimination", "pending"],
    )
    base["provinces"] = merge_into_list(
        base.get("provinces", []), live["provinces"], "name",
        ["value", "total", "support", "neutral", "qa", "worry", "criticism", "complaint",
         "implement", "fairness", "discrimination", "suggest", "other"],
    )
    base["languagePlatform"] = merge_into_list(
        base.get("languagePlatform", []), live["languages"], "name", ["value"],
    )

    # 态度构成
    att_extra = {
        "支持认可": c["support"], "中性信息": c["neutral"], "参与建议": c["suggest"],
        "问题": c["non_support"],
    }
    for item in base.setdefault("attitude", {}).get("macro", []):
        item["value"] = (item.get("value") or 0) + att_extra.get(item["name"], 0)
    detail_extra = {
        "支持认可": c["support"], "中性信息": c["neutral"], "参与建议": c["suggest"],
        "咨询疑问": live["nonSupport"].get("咨询疑问", 0), "担忧影响": live["nonSupport"].get("担忧影响", 0),
        "明确批评": live["nonSupport"].get("明确批评", 0), "投诉维权": live["nonSupport"].get("投诉维权", 0),
        "实施问题": live["nonSupport"].get("实施问题", 0), "公平争议": live["nonSupport"].get("公平争议", 0),
        "歧视偏见": live["nonSupport"].get("歧视偏见", 0), "不了解该法律": live["nonSupport"].get("不了解该法律", 0),
    }
    for item in base["attitude"].setdefault("detail", []):
        item["value"] = (item.get("value") or 0) + detail_extra.get(item["name"], 0)

    # 非支持构成（保留字段，供详情页/后续使用）
    base["nonSupport"] = merge_into_list(
        base.get("nonSupport", []),
        [{"name": k, "value": v} for k, v in live["nonSupport"].items()],
        "name", ["value"],
    )

    # 时间趋势（按天）
    if phase_only:
        base["trend"] = normalize_trend(live["trend_daily"], start=STATS_START[:10])
    else:
        trend_by = {}
        for t in base.get("trend", []):
            trend_by[t["date"]] = trend_by.get(t["date"], 0) + (t.get("value") or 0)
        for d, v in live["trend_daily"].items():
            trend_by[d] = trend_by.get(d, 0) + v
        base["trend"] = normalize_trend(trend_by)

    # 原话池（历史 + 实时）
    base["quotes"] = (base.get("quotes") or []) + [row_to_quote(r) for r in live["rows"][:QUOTE_LIMIT]]

    # 高热内容
    hot = (base.get("hotTop") or []) + live["hot"]
    seen = set()
    deduped = []
    for h in hot:
        key = (h.get("account", ""), h.get("title", ""), h.get("likes", 0))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(h)
    deduped.sort(key=lambda x: x.get("likes", 0), reverse=True)
    base["hotTop"] = deduped[:9]

    # 9 个平台独立展示 / 10 个固定重点地区 / 重点账号 / 小时趋势 / 统计口径
    base["platformDetail"] = live["platform_rows"]
    base["unknownPlatforms"] = live["unknown_platforms"]
    base["focusRegions"] = live["focus"]
    base["keyAccounts"] = live["key_accounts"]
    base["riskItems"] = [row_to_quote(r) for r in live["risks"]]
    base["trendHourly"] = live["hourly_rows"]
    base["phase"] = {
        "label": PHASE_LABEL,
        "statsStart": STATS_START,
        "includeHistory": bool(INCLUDE_HISTORY_BASELINE),
        "phaseOnly": phase_only,
    }
    base["stats"] = {
        "total": c["total"],
        "recent10m": c["recent10m"],
        "currentHour": c["current_hour"],
        "regionOpinions": c["region_total"],
        "support": c["support"],
        "neutral": c["neutral"],
        "nonSupport": c["non_support"],
        "supportRate": ts["supportRate"],
        "regionCount": c["region_count"],
        "platformCount": c["platform_count"],
        "platformCountAll": c["platform_count_all"],
        "minorityLang": c["minority"],
        "keyAccountCount": len(live["key_accounts"]),
        "statsStart": STATS_START,
    }

    base["generatedAt"] = now_iso()
    base["live"] = {
        "serverTime": now_iso(),
        "pending": live["pending"],
        "incidents": [row_to_quote(r) for r in live["rows"][:60]],
        "counts": {
            "total": c["total"], "support": c["support"], "nonSupport": c["non_support"],
            "region": c["region_total"], "minorityLang": c["minority"],
            "recent10m": c["recent10m"], "currentHour": c["current_hour"],
        },
    }
    return base


def key_accounts_payload():
    """重点账号模块的独立接口（GET /api/key-accounts）返回的聚合结果。"""
    live = compute_live_stats()
    return {
        "accounts": live["key_accounts"],
        "count": len(live["key_accounts"]),
        "updatedAt": now_iso(),
        "phase": {"label": PHASE_LABEL, "statsStart": STATS_START},
        "fields": ["account", "platform", "posts", "likes", "comments", "shares", "heat"],
    }
