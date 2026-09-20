from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PLATFORM_LABELS = {
    "wb": "微博",
    "xhs": "小红书",
    "dy": "抖音",
    "ks": "快手",
    "bili": "B站",
    "toutiao": "今日头条",
    "zhihu": "知乎",
    "wechat_mp": "微信公众号",
    "wechat_channels": "微信视频号",
}

TYPE_TO_ISSUE = {
    "information_gap": "咨询疑问",
    "consultation": "咨询疑问",
    "concern": "担忧影响",
    "criticism": "明确批评",
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
    if status == "normal":
        return "支持认可"
    if status == "neutral":
        return "中性信息"
    if status == "attention":
        return "中性信息"
    if status == "problematic":
        return "非支持/非肯定"
    return "待核实"


def _canonical_status_type(status: str, type_: str | None) -> tuple[str, str | None]:
    """Translate the retired v2.1 neutral/null pair without mutating source data."""
    if status == "neutral" and type_ in (None, "", "null"):
        return "attention", "neutral"
    return status, type_


def _source_label(row: dict) -> str:
    content_type = row.get("video_content_type") or row.get("source_type")
    if content_type:
        return f"MediaCrawler·{content_type}"
    record_type = row.get("record_type")
    if record_type == "video":
        return "MediaCrawler视频发布内容监测"
    if record_type == "comment":
        return "MediaCrawler评论监测"
    return "MediaCrawler帖子监测"


def to_suqi_record(row: dict) -> dict:
    platform_code = str(row.get("platform") or "").strip()
    platform = PLATFORM_LABELS.get(platform_code, platform_code or "其他")
    v2_status = str(row.get("status") or "").strip()
    v2_type = row.get("type")
    v2_status, v2_type = _canonical_status_type(v2_status, v2_type)
    region = _clean_region(row.get("ip_location"))
    language = str(row.get("language") or "汉语").strip() or "汉语"

    notes_parts = [f"v2_status={v2_status or 'unknown'}"]
    if v2_type:
        notes_parts.append(f"v2_type={v2_type}")
    for key in (
        "record_type", "source_type", "video_content_type", "source_type_method",
        "attitude_target", "analysis_basis", "video_attitude_scope",
        "comment_level", "parent_comment_id", "root_comment_id", "sub_comment_count",
    ):
        if row.get(key) not in (None, "", 0):
            notes_parts.append(f"{key}={row[key]}")
    if row.get("record_type") == "video":
        notes_parts.append(
            "video_multimodal_complete=" + str(bool(row.get("video_multimodal_complete"))).lower()
        )
    if row.get("source_keyword"):
        notes_parts.append(f"keyword={row['source_keyword']}")
    notes_parts.append(f"language={language}")
    if row.get("language_method"):
        notes_parts.append(f"language_method={row['language_method']}")
    if row.get("language_confidence"):
        notes_parts.append(f"language_confidence={row['language_confidence']}")

    for key in ("views", "favorites", "danmaku", "coins"):
        value = int(row.get(key) or 0)
        if value:
            notes_parts.append(f"{key}={value}")

    return {
        "uid": f"mediacrawler-{platform_code}-{row.get('sample_id', '')}",
        "collected_at": row.get("first_seen_time") or "",
        "published_at": row.get("publish_time") or "",
        "platform": platform,
        "source": _source_label(row),
        "account": row.get("author") or "",
        "text": row.get("content") or "",
        "url": row.get("url") or "",
        "region": region,
        "province": region,
        "ip_location": region,
        "language": language,
        "attitude": _attitude_from_v2(v2_status, v2_type),
        "issue_category": TYPE_TO_ISSUE.get(v2_type, "") if v2_type else "",
        "likes": row.get("likes") or 0,
        "comments": row.get("comments") or 0,
        "shares": row.get("shares") or 0,
        # Keep hierarchy metadata as first-class fields so the dashboard can build
        # real comment trees instead of parsing an opaque notes string.
        "record_type": row.get("record_type") or "",
        "content_id": row.get("content_id") or "",
        "comment_id": row.get("comment_id") or "",
        "parent_comment_id": row.get("parent_comment_id") or "",
        "root_comment_id": row.get("root_comment_id") or "",
        "comment_level": int(row.get("comment_level") or 0),
        "sub_comment_count": int(row.get("sub_comment_count") or 0),
        "notes": "; ".join(notes_parts),
        "origin": "mediacrawler_v2",
    }


def push_records(records: list[dict], ingest_url: str, timeout_seconds: int = 15) -> dict:
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


def _read_outbox(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
            except Exception:
                continue
    return rows


def _write_outbox(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        if path.exists():
            path.unlink()
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def deliver_with_outbox(
    new_records: list[dict],
    ingest_url: str,
    outbox_path: Path,
    timeout_seconds: int = 15,
) -> dict:
    pending = _read_outbox(outbox_path)
    combined = pending + list(new_records)

    unique = []
    seen = set()
    for row in combined:
        key = row.get("dedupe_key") or f"{row.get('platform','')}:{row.get('sample_id','')}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)

    if not unique:
        return {
            "ok": True,
            "sent": 0,
            "inserted": 0,
            "skipped": 0,
            "outbox_before": len(pending),
            "outbox_after": 0,
        }

    result = push_records(unique, ingest_url=ingest_url, timeout_seconds=timeout_seconds)
    if result.get("ok"):
        _write_outbox(outbox_path, [])
        result["outbox_before"] = len(pending)
        result["outbox_after"] = 0
    else:
        _write_outbox(outbox_path, unique)
        result["outbox_before"] = len(pending)
        result["outbox_after"] = len(unique)
    return result
