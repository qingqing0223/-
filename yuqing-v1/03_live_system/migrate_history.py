# -*- coding: utf-8 -*-
"""把第一阶段 data.js 的历史数据迁移进统一实时库（幂等，可重复执行）"""
import hashlib

import db
from config import BASE_DATA_JS
from ingest import attitude_bucket, is_minority_lang, issue_category, platform_group
from stats import parse_data_js


def _uid(prefix, *parts):
    key = "|".join(str(p or "") for p in parts)
    return f"{prefix}-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}"


def migrate(force=False):
    if db.get_meta("base_data") is not None and not force:
        print("[migrate] 历史基线已存在，跳过（--force 可重建）")
        return 0, 0

    data = parse_data_js(BASE_DATA_JS)
    db.set_meta("base_data", data)
    db.set_meta("seed_at", data.get("generatedAt", ""))

    quote_n = 0
    hot_n = 0
    for q in data.get("quotes", []):
        rec = {
            "uid": _uid("hist-q", q.get("platform"), q.get("date"), q.get("account"), q.get("text")),
            "collected_at": data.get("generatedAt") or "",
            "published_at": (q.get("date") or "")[:10],
            "platform": q.get("platform") or "",
            "platform_group": platform_group(q.get("platform") or ""),
            "source": q.get("source") or "",
            "account": q.get("account") or "",
            "text": q.get("text") or "",
            "url": "",
            "region": q.get("group") or q.get("region") or "",
            "province": "",
            "city": "",
            "ip_location": "",
            "language": q.get("language") or "中文",
            "is_minority": is_minority_lang(q.get("language") or "中文"),
            "attitude": q.get("attitude") or "待核实",
            "attitude_bucket": attitude_bucket(q.get("attitude") or ""),
            "issue_category": issue_category(q.get("attitude") or ""),
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "is_key": 0,
            "is_relevant": 1,
            "status": "accepted",
            "notes": "历史迁移（第一阶段 data.js）",
            "origin": "history",
        }
        if db.insert_incident(rec):
            quote_n += 1

    for h in data.get("hotTop", []):
        rec = {
            "uid": _uid("hist-hot", h.get("account"), h.get("title"), h.get("likes")),
            "collected_at": data.get("generatedAt") or "",
            "published_at": (h.get("date") or "")[:10],
            "platform": h.get("platform") or "",
            "platform_group": platform_group(h.get("platform") or ""),
            "source": "",
            "account": h.get("account") or "",
            "text": h.get("title") or "",
            "url": "",
            "region": "",
            "province": "",
            "city": "",
            "ip_location": "",
            "language": "中文",
            "is_minority": 0,
            "attitude": "高热内容",
            "attitude_bucket": "other",
            "issue_category": "",
            "likes": h.get("likes") or 0,
            "comments": h.get("comments") or 0,
            "shares": h.get("shares") or 0,
            "is_key": 1,
            "is_relevant": 1,
            "status": "accepted",
            "notes": "历史高热内容迁移",
            "origin": "history",
        }
        if db.insert_incident(rec):
            hot_n += 1

    print(f"[migrate] 历史原话入库 {quote_n} 条，高热内容 {hot_n} 条")
    return quote_n, hot_n


if __name__ == "__main__":
    import sys

    db.init_db()
    migrate(force="--force" in sys.argv)
