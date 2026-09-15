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

def _to_int(v):
    if v is None or v == "":
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().replace(",", "").replace("，", "")
    try:
        if s.lower().endswith("w"):
            return int(float(s[:-1]) * 10000)
        if s.endswith("万"):
            return int(float(s[:-1]) * 10000)
        if s.lower().endswith("k"):
            return int(float(s[:-1]) * 1000)
        return int(float(s))
    except Exception:
        return 0

def _to_iso_time(v):
    if v is None or v == "":
        return ""
    if isinstance(v, (int, float)):
        ts = float(v)
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat(timespec="seconds")
        except Exception:
            return str(v)
    s = str(v).strip()
    if s.isdigit():
        try:
            ts = float(s)
            if ts > 1e12:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat(timespec="seconds")
        except Exception:
            pass
    return s

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

    likes = _first(raw, "likes", "like_count", "liked_count", "digg_count", "liked_count", "thumbs_count")
    comments = _first(raw, "comments", "comment_count", "comments_count", "comment_num")
    shares = _first(raw, "shares", "share_count", "shared_count", "repost_count", "forward_count")

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
        "publish_time": _to_iso_time(publish_time),
        "first_seen_time": now,
        "ip_location": _str(region),
        "author": _str(author),
        "url": _str(url),
        "likes": _to_int(likes),
        "comments": _to_int(comments),
        "shares": _to_int(shares),
        "source_file": source_file,
    }
