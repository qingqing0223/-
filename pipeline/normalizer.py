from __future__ import annotations
from datetime import datetime, timezone
import hashlib

def _first(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return None

def _str(v):
    return "" if v is None else str(v)

def normalize_record(raw: dict, source_file: str = "", platform_hint: str = "") -> dict | None:
    title = _first(raw, "title", "note_title", "video_title")
    desc = _first(raw, "desc", "description", "aweme_desc")
    body = _first(raw, "content", "text", "note_text", "content_text", "comment_text")
    content = body or desc or title
    if content is None or not _str(content).strip():
        return None

    context = title or desc or ""
    content_id = _first(raw, "content_id", "aweme_id", "note_id", "video_id", "photo_id", "id", "mid")
    comment_id = _first(raw, "comment_id", "cid")
    platform = _first(raw, "platform", "source_platform", "source") or platform_hint
    region = _first(raw, "ip_location", "region", "province", "ip_region")
    publish_time = _first(raw, "publish_time", "create_time", "created_at", "create_date_time", "time")
    url = _first(raw, "url", "note_url", "video_url", "aweme_url", "share_url", "detail_url")
    author = _first(raw, "author", "nickname", "user_name", "user_nickname", "sec_user_name")
    source_keyword = _first(raw, "source_keyword", "keyword", "search_keyword")

    sample_id = _first(raw, "sample_id", "comment_id", "cid", "content_id", "aweme_id", "note_id", "video_id", "photo_id", "id", "mid")
    if sample_id is None:
        basis = f"{platform}|{source_file}|{content}|{context}|{publish_time}|{author}"
        sample_id = hashlib.sha256(basis.encode("utf-8", "ignore")).hexdigest()[:24]

    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    platform = _str(platform).strip()
    return {
        "sample_id": _str(sample_id),
        "dedupe_key": f"{platform}:{_str(sample_id)}",
        "platform": platform,
        "content_id": _str(content_id),
        "comment_id": _str(comment_id),
        "content": _str(content).strip(),
        "context": _str(context).strip(),
        "source_keyword": _str(source_keyword),
        "publish_time": _str(publish_time),
        "first_seen_time": now,
        "ip_location": _str(region),
        "author": _str(author),
        "url": _str(url),
        "source_file": source_file,
    }
