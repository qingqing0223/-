from __future__ import annotations
from datetime import datetime, timezone
import hashlib

from .language_detector import detect_language


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


def _tag_text(raw: dict) -> str:
    tags = _first(raw, "tag_list", "tags", "hashtags", "topic_list")
    if not tags:
        return ""
    if isinstance(tags, str):
        return tags.strip()
    names = []
    if isinstance(tags, list):
        for item in tags:
            if isinstance(item, dict):
                name = item.get("name") or item.get("title") or item.get("tag_name")
                if name:
                    names.append(str(name).strip())
            elif item:
                names.append(str(item).strip())
    return " ".join(x for x in names if x)


def _join_unique(parts: list[str]) -> str:
    out = []
    seen = set()
    for part in parts:
        text = _str(part).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return "\n".join(out)


def _detect_record_type(raw: dict, platform: str, comment_id) -> str:
    if comment_id:
        return "comment"

    raw_type = _str(_first(
        raw, "type", "note_type", "media_type", "content_type", "video_type",
        "aweme_type", "item_type"
    )).strip().lower()

    image_list = _first(raw, "image_list", "images", "note_images", "pictures", "pics")
    video_types = {"video", "short_video", "aweme", "movie", "zvideo"}
    if image_list and raw_type not in video_types:
        return "post"

    video_evidence = _first(
        raw, "video_url", "video_download_url", "play_url", "video_play_addr",
        "video_duration", "duration", "video_id"
    )
    if raw_type in video_types or video_evidence:
        return "video"

    # Douyin/Kuaishou exports are video-first. Other platforms are mixed and only
    # become video when their exported type/URL/id gives explicit evidence.
    if platform in {"dy", "ks"}:
        return "video"
    return "post"


def normalize_record(raw: dict, source_file: str = "", platform_hint: str = "") -> dict | None:
    title = _first(raw, "title", "note_title", "video_title")
    desc = _first(raw, "desc", "description", "aweme_desc")
    body = _first(raw, "content", "text", "note_text", "content_text", "comment_text", "message")
    tags = _tag_text(raw)

    asr_text = _first(raw, "asr_text", "transcript_text", "speech_text")
    ocr_text = _first(raw, "ocr_text", "subtitle_text", "screen_text")

    content = body or desc or title
    if content is None or not _str(content).strip():
        return None

    context = title or desc or ""
    content_id = _first(
        raw, "content_id", "aweme_id", "note_id", "video_id", "photo_id",
        "dynamic_id", "id", "mid"
    )
    comment_id = _first(raw, "comment_id", "cid", "rpid")
    platform = _first(raw, "platform", "source_platform", "source") or platform_hint
    platform = _str(platform).strip()
    region = _first(raw, "ip_location", "region", "province", "ip_region")
    publish_time = _first(
        raw, "publish_time", "create_time", "created_time", "created_at",
        "create_date_time", "pub_ts", "ctime", "time"
    )
    url = _first(
        raw, "url", "note_url", "video_url", "content_url", "aweme_url",
        "share_url", "detail_url"
    )
    author = _first(raw, "author", "nickname", "user_name", "user_nickname", "sec_user_name")
    source_keyword = _first(raw, "source_keyword", "keyword", "search_keyword")

    likes = _first(
        raw, "likes", "like_count", "liked_count", "digg_count", "thumbs_count",
        "voteup_count", "total_liked"
    )
    comments = _first(
        raw, "comments", "comment_count", "comments_count", "comment_num",
        "video_comment", "total_replay_num", "total_comments", "reply_count"
    )
    shares = _first(
        raw, "shares", "share_count", "shared_count", "repost_count", "forward_count",
        "video_share_count", "total_forwards"
    )
    views = _first(raw, "views", "view_count", "play_count", "video_play_count")
    favorites = _first(raw, "favorites", "favorite_count", "video_favorite_count")
    danmaku = _first(raw, "danmaku", "danmaku_count", "video_danmaku")
    coins = _first(raw, "coins", "coin_count", "video_coin_count")

    record_type = _detect_record_type(raw, platform, comment_id)
    if record_type == "comment":
        attitude_target = "audience_comment"
    elif record_type == "video":
        attitude_target = "publisher_video"
    else:
        attitude_target = "publisher_post"

    if record_type == "video":
        analysis_text = _join_unique([
            _str(title), _str(desc), _str(body), tags, _str(asr_text), _str(ocr_text)
        ])
        evidence = []
        if title or desc or body:
            evidence.append("caption")
        if tags:
            evidence.append("tags")
        if asr_text:
            evidence.append("asr")
        if ocr_text:
            evidence.append("ocr")
        analysis_basis = "+".join(evidence) or "caption"
    else:
        analysis_text = _join_unique([_str(content), _str(context)])
        analysis_basis = "comment_text" if record_type == "comment" else "post_text"

    language_info = detect_language(raw, analysis_text or content)

    sample_id = _first(
        raw, "sample_id", "comment_id", "cid", "rpid", "content_id", "aweme_id",
        "note_id", "video_id", "photo_id", "dynamic_id", "id", "mid"
    )
    if sample_id is None:
        basis = f"{platform}|{source_file}|{content}|{context}|{publish_time}|{author}"
        sample_id = hashlib.sha256(basis.encode("utf-8", "ignore")).hexdigest()[:24]

    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return {
        "sample_id": _str(sample_id),
        "dedupe_key": f"{platform}:{_str(sample_id)}",
        "platform": platform,
        "content_id": _str(content_id),
        "comment_id": _str(comment_id),
        "record_type": record_type,
        "attitude_target": attitude_target,
        "analysis_basis": analysis_basis,
        "analysis_text": analysis_text,
        "content": _str(content).strip(),
        "context": _str(context).strip(),
        "tag_text": tags,
        "asr_text": _str(asr_text).strip(),
        "ocr_text": _str(ocr_text).strip(),
        "source_keyword": _str(source_keyword),
        "publish_time": _to_iso_time(publish_time),
        "first_seen_time": now,
        "ip_location": _str(region),
        "language": language_info["language"],
        "language_method": language_info["language_method"],
        "language_confidence": language_info["language_confidence"],
        "language_script": language_info["language_script"],
        "author": _str(author),
        "url": _str(url),
        "likes": _to_int(likes),
        "comments": _to_int(comments),
        "shares": _to_int(shares),
        "views": _to_int(views),
        "favorites": _to_int(favorites),
        "danmaku": _to_int(danmaku),
        "coins": _to_int(coins),
        "source_file": source_file,
    }
