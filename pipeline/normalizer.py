from __future__ import annotations
from datetime import datetime, timedelta, timezone
import hashlib
from urllib.parse import urlsplit, urlunsplit

from .language_detector import detect_language


def _first(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return None


def _first_nested(d: dict, parent_keys: tuple[str, ...], *keys):
    value = _first(d, *keys)
    if value is not None:
        return value
    for parent_key in parent_keys:
        parent = d.get(parent_key)
        if isinstance(parent, dict):
            value = _first(parent, *keys)
            if value is not None:
                return value
    return None


def _str(v):
    return "" if v is None else str(v)


def _keyword_list(value) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return list(dict.fromkeys(str(item).strip() for item in values if str(item or "").strip()))


def _canonical_url(value) -> str:
    text = _str(value).strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))
    except Exception:
        return text


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


def _to_optional_int(v):
    """Parse a public counter without turning unavailable data into a false zero."""
    if v is None or str(v).strip() == "":
        return None
    parsed = _to_int(v)
    text = str(v).strip().replace(",", "").replace("，", "")
    if parsed == 0 and text not in {"0", "0.0"}:
        return None
    return parsed


BEIJING_TZ = timezone(timedelta(hours=8))


def _to_iso_time(v, output_tz=None):
    if v is None or v == "":
        return ""
    if isinstance(v, (int, float)):
        ts = float(v)
        if ts > 1e12:
            ts /= 1000.0
        try:
            target_tz = output_tz or datetime.now().astimezone().tzinfo
            return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(target_tz).isoformat(timespec="seconds")
        except Exception:
            return str(v)
    s = str(v).strip()
    if s.isdigit():
        try:
            ts = float(s)
            if ts > 1e12:
                ts /= 1000.0
            target_tz = output_tz or datetime.now().astimezone().tzinfo
            return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(target_tz).isoformat(timespec="seconds")
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

    if platform in {"dy", "ks"}:
        return "video"
    return "post"


def _nonzero_id(value) -> str:
    text = _str(value).strip()
    if text.lower() in {"", "0", "none", "null", "false"}:
        return ""
    return text


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
        raw, "content_id", "article_id", "group_id", "item_id", "aweme_id", "note_id",
        "video_id", "photo_id", "dynamic_id", "id", "mid"
    )
    comment_id = _first(raw, "comment_id", "cid", "rpid")
    parent_comment_id = _nonzero_id(_first(
        raw, "parent_comment_id", "parent_id", "reply_comment_id",
        "reply_to_comment_id", "reply_to_id", "parent_rpid"
    ))
    root_comment_id = _nonzero_id(_first(raw, "root_comment_id", "root_id", "root_rpid"))
    sub_comment_count = _to_int(_first(raw, "sub_comment_count", "sub_comments_count", "reply_count"))
    comment_reply_count_raw = _first(raw, "sub_comment_count", "sub_comments_count", "reply_count")

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
    author_id = _first(raw, "creator_hash", "user_id", "author_id", "uid", "sec_uid", "mid")
    author_avatar = _first(raw, "avatar", "avatar_url", "user_avatar", "head_url")
    author_profile_url = _first(raw, "user_url", "author_url", "profile_url", "creator_url")
    if platform == "ks":
        if isinstance(author, dict):
            author = None
        author = author or _first_nested(
            raw, ("user", "user_info", "author", "creator"),
            "name", "nickname", "user_name", "user_nickname"
        )
        author_id = author_id or _first_nested(
            raw, ("user", "user_info", "author", "creator"),
            "user_id", "author_id", "uid", "creator_id", "kwai_id"
        )
        author_avatar = author_avatar or _first_nested(
            raw, ("user", "user_info", "author", "creator"),
            "avatar", "avatar_url", "user_avatar", "head_url"
        )
        author_profile_url = author_profile_url or _first_nested(
            raw, ("user", "user_info", "author", "creator"),
            "user_url", "author_url", "profile_url", "creator_url"
        )
    reply_to_author = _first(raw, "reply_to_nickname", "reply_user_name", "reply_to_user_name")
    source_keyword = _first(raw, "source_keyword", "keyword", "search_keyword")

    likes = _first(
        raw, "likes", "like_count", "liked_count", "digg_count", "thumbs_count",
        "voteup_count", "total_liked", "comment_like_count", "realLikedCount",
        "likedCount", "likeCount", "real_liked_count"
    )
    comments = _first(
        raw, "comments", "comment_count", "comments_count", "comment_num",
        "video_comment", "total_replay_num", "total_comments", "reply_count"
    )
    shares = _first(
        raw, "shares", "share_count", "shared_count", "repost_count", "forward_count",
        "video_share_count", "total_forwards"
    )
    kuaishou_shares = _first(raw, "shares", "share_count", "shared_count", "video_share_count")
    reposts = _first(raw, "repost_count", "forward_count", "total_forwards")
    views = _first(raw, "views", "view_count", "play_count", "video_play_count", "viewd_count")
    favorites = _first(raw, "favorites", "favorite_count", "video_favorite_count", "collected_count")
    danmaku = _first(raw, "danmaku", "danmaku_count", "video_danmaku")
    coins = _first(raw, "coins", "coin_count", "video_coin_count")
    follower_count = _first_nested(
        raw, ("user", "user_info", "author", "creator"),
        "fan", "fan_count", "fans", "fans_count", "follower_count", "followers_count"
    )
    following_count = _first_nested(
        raw, ("user", "user_info", "author", "creator"),
        "follow", "following", "following_count", "follow_count"
    )
    account_type = _first_nested(
        raw, ("user", "user_info", "author", "creator"),
        "account_type", "user_type", "verification_type", "verified_type"
    )
    account_region = _first_nested(
        raw, ("user", "user_info", "author", "creator"),
        "account_region", "ip_location", "ip_region", "province", "region"
    )
    institution = _first_nested(
        raw, ("user", "user_info", "author", "creator"),
        "institution", "organization", "organisation", "agency"
    )

    record_type = _detect_record_type(raw, platform, comment_id)
    if record_type == "comment":
        attitude_target = "audience_comment"
        if not root_comment_id:
            root_comment_id = parent_comment_id or _str(comment_id)
        comment_level = 2 if parent_comment_id else 1
    elif record_type == "video":
        attitude_target = "publisher_video"
        comment_level = 0
    else:
        attitude_target = "publisher_post"
        comment_level = 0

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
        raw, "sample_id", "comment_id", "cid", "rpid", "content_id", "article_id",
        "group_id", "item_id", "aweme_id", "note_id", "video_id", "photo_id",
        "dynamic_id", "id", "mid"
    )
    if platform == "ks":
        stable_id = _str(comment_id if record_type == "comment" else content_id).strip()
        canonical_url = _canonical_url(url)
        if stable_id:
            sample_id = stable_id
        elif canonical_url:
            sample_id = hashlib.sha256(canonical_url.encode("utf-8", "ignore")).hexdigest()[:24]
    if sample_id is None:
        basis = f"{platform}|{source_file}|{content}|{context}|{publish_time}|{author}"
        sample_id = hashlib.sha256(basis.encode("utf-8", "ignore")).hexdigest()[:24]

    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    metric_parser = _to_optional_int if platform == "ks" else _to_int
    metric_values = {
        "likes": metric_parser(likes),
        "comments": metric_parser(comments),
        "shares": metric_parser(kuaishou_shares if platform == "ks" else shares),
        "reposts": metric_parser(reposts),
        "views": metric_parser(views),
        "favorites": metric_parser(favorites),
    }
    metric_missing_reasons = {
        name: "field_missing_or_unparseable"
        for name, value in metric_values.items()
        if value is None
    }
    return {
        "sample_id": _str(sample_id),
        "dedupe_key": f"{platform}:{_str(sample_id)}",
        "platform": platform,
        "content_id": _str(content_id),
        "comment_id": _str(comment_id),
        "parent_comment_id": parent_comment_id,
        "root_comment_id": root_comment_id,
        "comment_level": comment_level,
        "sub_comment_count": sub_comment_count,
        "comment_reply_count": (
            _to_optional_int(comment_reply_count_raw) if platform == "ks" else sub_comment_count
        ),
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
        "source_keywords": _keyword_list(source_keyword),
        "publish_time": _to_iso_time(publish_time, BEIJING_TZ if platform == "ks" else None),
        "first_seen_time": now,
        "ip_location": _str(region),
        "language": language_info["language"],
        "language_method": language_info["language_method"],
        "language_confidence": language_info["language_confidence"],
        "language_script": language_info["language_script"],
        "author": _str(author),
        "author_id": _str(author_id),
        "author_avatar": _str(author_avatar),
        "author_profile_url": _str(author_profile_url),
        "account_type": _str(account_type) or None,
        "follower_count": _to_optional_int(follower_count) if platform == "ks" else _to_int(follower_count),
        "following_count": _to_optional_int(following_count) if platform == "ks" else _to_int(following_count),
        "account_region": _str(account_region) or None,
        "institution": _str(institution) or None,
        "reply_to_author": _str(reply_to_author),
        "url": _str(url),
        "likes": metric_values["likes"],
        "comments": metric_values["comments"],
        "shares": metric_values["shares"],
        "reposts": metric_values["reposts"],
        "views": metric_values["views"],
        "favorites": metric_values["favorites"],
        "metric_missing_reasons": metric_missing_reasons,
        "danmaku": _to_int(danmaku),
        "coins": _to_int(coins),
        "source_file": source_file,
    }
