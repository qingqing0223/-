from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

PLATFORM_LABELS = {
    "wb": "微博",
    "xhs": "小红书",
    "dy": "抖音",
    "ks": "快手",
}

TYPE_TO_ISSUE = {
    "information_gap": "咨询疑问",
    "consultation": "咨询疑问",
    "concern": "担忧影响",
    "criticism": "明确批评",
    # 苏琦当前 stats.py 仍把“质疑”并入“明确批评”；原始 v2_type 会保留在 notes 中。
    "skepticism": "明确批评",
    "implementation_issue": "实施问题",
    "fairness_dispute": "公平争议",
    "complaint_rights": "投诉维权",
    "discriminatory_expression": "歧视偏见",
}


def _clean_region(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    for prefix in ("IP属地：", "IP属地:", "IP属地", "来自"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text


def _attitude_from_v2(status: str, type_: str | None) -> str:
    """Keep the v2 decision as the source of truth, only translating for the dashboard schema."""
    if status == "normal":
        return "支持认可"
    if status == "neutral":
        return "中性信息"
    if status == "attention":
        # v2 attention = information gap / consultation, not an explicit problem judgement.
        return "中性信息"
    if status == "problematic":
        return "非支持/非肯定"
    return "待核实"


def to_suqi_record(row: dict) -> dict:
    platform_code = str(row.get("platform") or "").strip()
    platform = PLATFORM_LABELS.get(platform_code, platform_code or "其他")
    v2_status = str(row.get("status") or "").strip()
    v2_type = row.get("type")
    region = _clean_region(row.get("ip_location"))

    notes_parts = [f"v2_status={v2_status or 'unknown'}"]
    if v2_type:
        notes_parts.append(f"v2_type={v2_type}")
    if row.get("source_keyword"):
        notes_parts.append(f"keyword={row['source_keyword']}")

    return {
        "uid": f"mediacrawler-{platform_code}-{row.get('sample_id', '')}",
        "collected_at": row.get("first_seen_time") or "",
        "published_at": row.get("publish_time") or "",
        "platform": platform,
        "source": "MediaCrawler关键词监测",
        "account": row.get("author") or "",
        "text": row.get("content") or "",
        "url": row.get("url") or "",
        "region": region,
        "province": region,
        "ip_location": region,
        "language": "中文",
        "attitude": _attitude_from_v2(v2_status, v2_type),
        "issue_category": TYPE_TO_ISSUE.get(v2_type, "") if v2_type else "",
        "likes": row.get("likes") or 0,
        "comments": row.get("comments") or 0,
        "shares": row.get("shares") or 0,
        "notes": "; ".join(notes_parts),
        "origin": "mediacrawler_v2",
    }


def push_records(
    records: list[dict],
    ingest_url: str,
    timeout_seconds: int = 15,
) -> dict:
    """POST one classified batch to Suqi's /api/ingest endpoint."""
    if not records:
        return {"ok": True, "sent": 0, "inserted": 0, "skipped": 0}

    url = os.environ.get("SUQI_INGEST_URL", "").strip() or ingest_url.strip()
    if not url:
        return {"ok": False, "sent": 0, "error": "missing ingest_url"}

    payload = {
        "origin": "mediacrawler_v2",
        "records": [to_suqi_record(r) for r in records],
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            result = json.loads(raw) if raw else {}
            return {
                "ok": True,
                "sent": len(records),
                "http_status": getattr(resp, "status", 200),
                **result,
            }
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "sent": len(records),
            "http_status": exc.code,
            "error": detail or str(exc),
        }
    except Exception as exc:
        return {
            "ok": False,
            "sent": len(records),
            "error": f"{type(exc).__name__}: {exc}",
        }
