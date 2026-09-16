from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

CN_TZ = timezone(timedelta(hours=8))


def now_cn() -> datetime:
    return datetime.now(CN_TZ)


def append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def stable_id(*parts: str) -> str:
    text = "|".join(str(x or "").strip() for x in parts)
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()[:24]


def clean_text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def parse_public_time(text: str, reference: datetime | None = None) -> str:
    """Best-effort parser for public display timestamps; empty when not reliable."""
    s = clean_text(text)
    if not s:
        return ""
    ref = reference or now_cn()

    m = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=CN_TZ).isoformat()
        except ValueError:
            pass

    m = re.search(r"(\d{1,2})月(\d{1,2})日", s)
    if m:
        try:
            dt = datetime(ref.year, int(m.group(1)), int(m.group(2)), tzinfo=CN_TZ)
            if dt > ref + timedelta(days=2):
                dt = dt.replace(year=ref.year - 1)
            return dt.isoformat()
        except ValueError:
            pass

    if "今天" in s:
        return ref.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    if "昨天" in s:
        return (ref - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    m = re.search(r"(\d+)\s*小时前", s)
    if m:
        return (ref - timedelta(hours=int(m.group(1)))).isoformat(timespec="seconds")
    m = re.search(r"(\d+)\s*分钟前", s)
    if m:
        return (ref - timedelta(minutes=int(m.group(1)))).isoformat(timespec="seconds")
    return ""


def make_record(
    *,
    platform: str,
    keyword: str,
    title: str,
    content: str,
    author: str = "",
    url: str = "",
    publish_time: str = "",
    record_type: str = "post",
    raw_text: str = "",
) -> dict:
    title = clean_text(title)
    content = clean_text(content)
    author = clean_text(author)
    url = clean_text(url)
    raw_text = clean_text(raw_text)
    basis = url or f"{title}|{content}|{author}|{keyword}"
    content_id = stable_id(platform, basis)
    return {
        "platform": platform,
        "content_id": content_id,
        "title": title,
        "content": content or title,
        "author": author,
        "url": url,
        "publish_time": publish_time,
        "source_keyword": keyword,
        "type": record_type,
        "raw_text": raw_text,
        "collected_at": now_cn().isoformat(timespec="seconds"),
    }
