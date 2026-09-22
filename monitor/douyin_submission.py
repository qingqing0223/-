from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Iterable

from pipeline.normalizer import normalize_record


BEIJING = timezone(timedelta(hours=8))

TABLES = {
    "table1_content.jsonl": "content_id",
    "table2_comments.jsonl": "comment_id",
    "table3_content_engagement.jsonl": "snapshot_key",
    "table4_comment_engagement.jsonl": "snapshot_key",
    "table5_accounts.jsonl": "account_key",
}


def _read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []

    rows: list[dict] = []
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except Exception:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _write_rows(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")

    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    tmp.replace(path)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _first(raw: dict, *keys):
    for key in keys:
        if key in raw:
            value = raw.get(key)
            if value is not None and value != "":
                return value
    return None


def _parse_time(value) -> datetime | None:
    if value in (None, ""):
        return None

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None
    else:
        text = str(value).strip()

        if not text:
            return None

        if text.isdigit():
            try:
                ts = float(text)
                if ts > 1e12:
                    ts /= 1000.0
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                return None
        else:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                dt = datetime.fromisoformat(text)
            except Exception:
                return None

    if dt.tzinfo is None:
        # 抖音项目中无时区的人工/本地时间按北京时间解释。
        dt = dt.replace(tzinfo=BEIJING)

    return dt.astimezone(BEIJING)


def _beijing_iso(value) -> str:
    dt = _parse_time(value)
    return dt.isoformat(timespec="seconds") if dt else ""


def _hour_bucket(value: datetime) -> str:
    dt = value.astimezone(BEIJING)
    return dt.replace(
        minute=0,
        second=0,
        microsecond=0,
    ).isoformat(timespec="seconds")


def _collection_time_from_path(path: Path) -> datetime | None:
    """Recover the crawler cycle start time from raw_runs/YYYYMMDD_HHMMSS/."""
    for part in path.parts:
        if re.fullmatch(r"\d{8}_\d{6}", part):
            try:
                return datetime.strptime(
                    part,
                    "%Y%m%d_%H%M%S",
                ).replace(tzinfo=BEIJING)
            except ValueError:
                return None
    return None


def _public_value(raw: dict, *keys):
    """Only return an explicitly present public value.

    0 is a real value. Missing values remain blank.
    """
    for key in keys:
        if key in raw:
            value = raw.get(key)
            if value is not None and value != "":
                return value
    return ""


def _metric(raw: dict, *keys):
    value = _public_value(raw, *keys)
    if value == "":
        return ""

    if isinstance(value, bool):
        return int(value)

    if isinstance(value, (int, float)):
        return int(value)

    text = str(value).strip().replace(",", "")
    try:
        low = text.lower()
        if low.endswith("w"):
            return int(float(low[:-1]) * 10000)
        if text.endswith("万"):
            return int(float(text[:-1]) * 10000)
        if low.endswith("k"):
            return int(float(low[:-1]) * 1000)
        return int(float(text))
    except Exception:
        return value


def _keyword_list(value) -> list[str]:
    if value in (None, ""):
        return []

    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        text = str(value)
        values = re.split(r"[;,，；]+", text)

    result = []
    seen = set()

    for item in values:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)

    return result


def _source_keywords(raw: dict, configured_keywords: list[str]) -> list[str]:
    result = []

    for key in ("source_keyword", "keyword", "search_keyword"):
        result.extend(_keyword_list(raw.get(key)))

    visible = "\n".join(
        str(raw.get(key) or "")
        for key in (
            "title",
            "desc",
            "description",
            "content",
            "text",
            "aweme_desc",
        )
    )

    # Fallback only. Search provenance above remains the primary evidence.
    for keyword in configured_keywords:
        if keyword and keyword in visible:
            result.append(keyword)

    return list(dict.fromkeys(x for x in result if x))


def _visible_text(raw: dict, record: dict) -> str:
    parts = [
        raw.get("title"),
        raw.get("desc"),
        raw.get("description"),
        raw.get("aweme_desc"),
        raw.get("content"),
        raw.get("text"),
        record.get("context"),
        record.get("content"),
        record.get("tag_text"),
    ]

    return "\n".join(
        str(x).strip()
        for x in parts
        if x is not None and str(x).strip()
    )


def _topic_decision(
    raw: dict,
    record: dict,
    manual_include: set[str],
    manual_exclude: set[str],
    require_topic: bool,
) -> tuple[bool, str]:
    content_id = str(
        record.get("content_id")
        or record.get("sample_id")
        or ""
    ).strip()

    if content_id in manual_exclude:
        return False, "\u4eba\u5de5\u590d\u6838\u6392\u9664"

    if content_id in manual_include:
        return True, ""

    if not require_topic:
        return True, ""

    visible = _visible_text(raw, record)
    compact = re.sub(r"\s+", "", visible)

    raw_visible = "\n".join(
        str(raw.get(key) or "").strip()
        for key in (
            "title",
            "desc",
            "description",
            "aweme_desc",
            "content",
            "text",
        )
        if str(raw.get(key) or "").strip()
    )

    tag_probe = (raw_visible or visible).strip()

    # Reject content made almost entirely of hashtags.
    without_tags = re.sub(r"#[^#\s]+", "", tag_probe)
    without_tags = re.sub(
        r"[#\s\uff0c,\u3002.!??\uff1f\u3001;\uff1b:\uff1a]+",
        "",
        without_tags,
    )

    if "#" in tag_probe and not without_tags:
        return False, "\u4ec5\u77ed\u6807\u7b7e\u547d\u4e2d\uff0c\u9700\u4eba\u5de5\u6838\u9a8c"

    # 2026-09-21 rule:
    # Search provenance alone is NOT enough.
    # But if the exact query phrase really appears in title/body,
    # it is explicit topic evidence even when it does not contain
    # the literal word "publicity week".
    normalized_visible = re.sub(
        r"[\s\uff0c,\u3002.!??\uff1f\u3001;\uff1b:\uff1a\-_\u2014]+",
        "",
        visible,
    )

    provenance_keywords = []

    for key in (
        "source_keyword",
        "keyword",
        "search_keyword",
    ):
        provenance_keywords.extend(
            _keyword_list(raw.get(key))
        )

    for keyword in provenance_keywords:
        normalized_keyword = re.sub(
            r"[\s\uff0c,\u3002.!??\uff1f\u3001;\uff1b:\uff1a\-_\u2014]+",
            "",
            str(keyword),
        )

        if (
            len(normalized_keyword) >= 4
            and normalized_keyword in normalized_visible
        ):
            return True, ""

    # Preserve the original strict event rule.
    if "\u5ba3\u4f20\u5468" not in compact:
        return False, "\u6b63\u6587\u672a\u660e\u786e\u51fa\u73b0\u5ba3\u4f20\u5468"

    if (
        "\u6c11\u65cf\u56e2\u7ed3" not in compact
        and "\u4fc3\u8fdb\u6cd5" not in compact
    ):
        return False, "\u5ba3\u4f20\u5468\u4f46\u672a\u80fd\u786e\u8ba4\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65\u4e3b\u9898"

    return True, ""


def _merge_row(existing: dict, incoming: dict, key_name: str) -> dict:
    out = dict(existing)

    for key, value in incoming.items():
        if key == "matched_keywords":
            continue
        if key not in out or value not in (None, ""):
            out[key] = value

    matches = set(_keyword_list(existing.get("matched_keywords")))
    matches.update(_keyword_list(incoming.get("matched_keywords")))
    out["matched_keywords"] = sorted(matches)

    out[key_name] = str(
        out.get(key_name)
        or incoming.get(key_name)
        or ""
    ).strip()

    return out


def _upsert_rows(path: Path, rows: Iterable[dict], key_name: str) -> int:
    existing = {
        str(row.get(key_name) or "").strip(): row
        for row in _read_rows(path)
        if str(row.get(key_name) or "").strip()
    }

    before = len(existing)

    for row in rows:
        key = str(row.get(key_name) or "").strip()
        if not key:
            continue

        if key in existing:
            existing[key] = _merge_row(existing[key], row, key_name)
        else:
            existing[key] = row

    _write_rows(
        path,
        [existing[key] for key in sorted(existing)],
    )

    return len(existing) - before


def _upsert_snapshot_rows(path: Path, rows: Iterable[dict]) -> int:
    """One row per object per Beijing hour.

    Same-hour refreshes update that hour's row.
    Different hours are never overwritten.
    """
    existing = {
        str(row.get("snapshot_key") or ""): row
        for row in _read_rows(path)
        if row.get("snapshot_key")
    }

    before = len(existing)

    for row in rows:
        key = str(row.get("snapshot_key") or "")
        if key:
            existing[key] = row

    _write_rows(
        path,
        [existing[key] for key in sorted(existing)],
    )

    return len(existing) - before


def _normalize_douyin_submission_record(
    raw: dict,
    source_file: str,
) -> dict | None:
    """Normalize Douyin records for Tables 1-5.

    Public normalizer intentionally drops records with no text.
    Douyin can expose valid empty-text/image comments, so preserve those
    for collection tables when stable comment/video IDs are present.
    """
    record = normalize_record(
        raw,
        source_file=source_file,
        platform_hint="dy",
    )

    if record is not None:
        return record

    comment_id = str(
        raw.get("comment_id") or ""
    ).strip()

    content_id = str(
        raw.get("aweme_id")
        or raw.get("content_id")
        or ""
    ).strip()

    if not comment_id or not content_id:
        return None

    parent_raw = str(
        raw.get("parent_comment_id") or ""
    ).strip()

    parent_comment_id = (
        ""
        if parent_raw in {"", "0", "None", "null"}
        else parent_raw
    )

    root_raw = str(
        raw.get("root_comment_id") or ""
    ).strip()

    root_comment_id = (
        root_raw
        if root_raw not in {"", "0", "None", "null"}
        else (parent_comment_id or comment_id)
    )

    return {
        "platform": "dy",
        "record_type": "comment",
        "content_id": content_id,
        "comment_id": comment_id,
        "parent_comment_id": parent_comment_id,
        "root_comment_id": root_comment_id,
        "comment_level": 2 if parent_comment_id else 1,
        "publish_time": _first(
            raw,
            "create_time",
            "publish_time",
            "create_date",
        ),
        "author": str(
            raw.get("nickname")
            or raw.get("author")
            or ""
        ),
        "author_id": str(
            raw.get("creator_hash")
            or raw.get("user_id")
            or raw.get("uid")
            or ""
        ),
        "ip_location": str(
            raw.get("ip_location")
            or ""
        ),
        "content": str(
            raw.get("content")
            or ""
        ),
        "pictures": raw.get("pictures") or "",
    }


def _in_monitoring_time(record: dict, monitoring_start: str) -> bool:
    if not monitoring_start:
        return True

    published = _parse_time(record.get("publish_time"))
    start = _parse_time(monitoring_start)

    if not published:
        return False

    if not start:
        return True

    return published >= start


def _latest_content_snapshots(rows: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}

    for row in rows:
        content_id = str(row.get("content_id") or "").strip()
        if not content_id:
            continue

        current = latest.get(content_id)

        if current is None:
            latest[content_id] = row
            continue

        if str(row.get("snapshot_time") or "") > str(
            current.get("snapshot_time") or ""
        ):
            latest[content_id] = row

    return latest


def _number_or_none(value):
    if value in ("", None):
        return None
    try:
        return int(float(value))
    except Exception:
        return None


def _aggregate_metrics(rows: list[dict], field: str):
    values = [
        _number_or_none(row.get(field))
        for row in rows
    ]
    values = [x for x in values if x is not None]

    if not values:
        return ""

    return sum(values)


def _build_accounts(
    contents: list[dict],
    content_snapshot_rows: list[dict],
    existing_accounts: list[dict],
    collection_time: str,
) -> list[dict]:
    latest = _latest_content_snapshots(content_snapshot_rows)

    old = {
        str(row.get("account_key") or ""): row
        for row in existing_accounts
        if str(row.get("account_key") or "")
    }

    grouped: dict[str, dict] = {}

    for content in contents:
        account_id = str(content.get("account_id") or "").strip()
        account_name = str(content.get("account_name") or "").strip()

        if not account_id and not account_name:
            continue

        account_key = (
            f"id:{account_id}"
            if account_id
            else f"name:{account_name}"
        )

        stat = grouped.setdefault(
            account_key,
            {
                "account_key": account_key,
                "account_id": account_id,
                "platform": "抖音",
                "account_name": account_name,
                "profile_url": "",
                "account_type": "",
                "follower_count": "",
                "following_count": "",
                "region": "",
                "organization": "",
                "is_key_account": "",
                "content_ids": [],
                "snapshots": [],
            },
        )

        for field in (
            "profile_url",
            "account_type",
            "region",
            "organization",
        ):
            value = content.get(field)
            if value not in (None, ""):
                stat[field] = value

        content_id = str(content.get("content_id") or "").strip()
        if content_id:
            stat["content_ids"].append(content_id)

            snap = latest.get(content_id)
            if snap:
                stat["snapshots"].append(snap)

    result = []

    for account_key, stat in grouped.items():
        snaps = stat.pop("snapshots")
        content_ids = list(dict.fromkeys(stat.pop("content_ids")))

        interaction_parts = []

        snapshot_times = [
            str(s.get("snapshot_time") or "")
            for s in snaps
            if str(s.get("snapshot_time") or "")
        ]
        account_collection_time = (
            max(snapshot_times)
            if snapshot_times
            else collection_time
        )

        row = {
            **stat,
            "related_post_count": len(content_ids),
            "view_count": _aggregate_metrics(snaps, "view_count"),
            "like_count": _aggregate_metrics(snaps, "like_count"),
            "comment_count": _aggregate_metrics(snaps, "comment_count"),
            "repost_count": _aggregate_metrics(snaps, "repost_count"),
            "share_count": _aggregate_metrics(snaps, "share_count"),
            "favorite_count": _aggregate_metrics(snaps, "favorite_count"),
            "total_engagement": "",
            "collection_time": account_collection_time,
        }

        for field in (
            "like_count",
            "comment_count",
            "repost_count",
            "share_count",
            "favorite_count",
        ):
            value = _number_or_none(row[field])
            if value is not None:
                interaction_parts.append(value)

        if interaction_parts:
            row["total_engagement"] = sum(interaction_parts)

        if account_key in old:
            preserved = dict(old[account_key])

            for field in (
                "profile_url",
                "account_type",
                "follower_count",
                "following_count",
                "region",
                "organization",
                "is_key_account",
            ):
                if row.get(field) in ("", None) and preserved.get(field) not in ("", None):
                    row[field] = preserved[field]

        result.append(row)

    return sorted(
        result,
        key=lambda x: (
            str(x.get("account_name") or ""),
            str(x.get("account_key") or ""),
        ),
    )



def _load_douyin_comment_ip_enrichment(
    path_value,
) -> dict[str, str]:
    """Load previously collected public comment IP regions.

    Raw records always have priority. This mapping is only used
    when the current raw record has no public IP location.
    """
    if not path_value:
        return {}

    path = Path(str(path_value))

    if not path.exists() or not path.is_file():
        return {}

    result: dict[str, str] = {}

    for row in _read_rows(path):
        if str(row.get("record_type") or "") != "comment":
            continue

        comment_id = str(
            row.get("comment_id") or ""
        ).strip()

        ip_location = str(
            row.get("ip_location") or ""
        ).strip()

        if comment_id and ip_location:
            result[comment_id] = ip_location

    return result


def export_douyin_submission(
    raw_files: list[Path],
    cfg: dict,
    repo_root: Path,
    node_id: str,
    *,
    now: datetime | None = None,
) -> dict:
    """Merge one Douyin cycle into formal Tables 1-5.

    Table 1/2 are current cumulative datasets.
    Table 3/4 use object-id + Beijing-hour snapshot keys.
    Table 5 is rebuilt from the cleaned Table 1 and latest Table 3 values.
    """

    now_dt = now or datetime.now(BEIJING)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=BEIJING)
    now_dt = now_dt.astimezone(BEIJING)

    now_text = now_dt.isoformat(timespec="seconds")
    current_bucket = _hour_bucket(now_dt)
    date_text = now_dt.date().isoformat()

    safe_node = "".join(
        ch if ch.isalnum() or ch in "-_."
        else "_"
        for ch in str(node_id or "dy01")
    )

    output = (
        repo_root
        / "data_submissions"
        / "douyin"
        / f"{date_text}_{safe_node}"
    )
    output.mkdir(parents=True, exist_ok=True)

    keywords = [
        str(x).strip()
        for x in cfg.get("keywords", [])
        if str(x).strip()
    ]

    monitoring_start = str(
        cfg.get("monitoring_start_time") or ""
    )

    require_topic = bool(
        cfg.get("douyin_submission_require_topic", True)
    )

    manual_include = set(
        str(x).strip()
        for x in cfg.get(
            "douyin_submission_include_content_ids",
            [],
        )
        if str(x).strip()
    )

    manual_exclude = set(
        str(x).strip()
        for x in cfg.get(
            "douyin_submission_exclude_content_ids",
            [],
        )
        if str(x).strip()
    )

    table1_path = output / "table1_content.jsonl"
    table2_path = output / "table2_comments.jsonl"
    table3_path = output / "table3_content_engagement.jsonl"
    table4_path = output / "table4_comment_engagement.jsonl"
    table5_path = output / "table5_accounts.jsonl"
    manifest_path = output / "manifest.json"

    comment_ip_enrichment = (
        _load_douyin_comment_ip_enrichment(
            cfg.get(
                "douyin_submission_enrichment_jsonl",
                "",
            )
        )
    )

    existing_contents = {
        str(row.get("content_id") or ""): row
        for row in _read_rows(table1_path)
        if str(row.get("content_id") or "")
    }

    # Explicit manual exclusions also remove rows retained by a prior run.
    for content_id in manual_exclude:
        existing_contents.pop(content_id, None)

    existing_comments = {
        str(row.get("comment_id") or ""): row
        for row in _read_rows(table2_path)
        if str(row.get("comment_id") or "")
    }

    raw_rows: list[tuple[Path, dict]] = []

    for path in raw_files:
        for raw in _read_rows(path):
            raw_rows.append((path, raw))

    valid_current_content_ids: set[str] = set()
    excluded_reasons: dict[str, int] = {}

    # Pass 1: establish valid current parent content IDs.
    for raw_path, raw in raw_rows:
        record = _normalize_douyin_submission_record(
            raw,
            raw_path.name,
        )

        if not record or record.get("record_type") == "comment":
            continue

        if not _in_monitoring_time(record, monitoring_start):
            excluded_reasons["发布时间早于监测起点或缺失"] = (
                excluded_reasons.get("发布时间早于监测起点或缺失", 0) + 1
            )
            continue

        valid, reason = _topic_decision(
            raw,
            record,
            manual_include,
            manual_exclude,
            require_topic,
        )

        if not valid:
            excluded_reasons[reason] = excluded_reasons.get(reason, 0) + 1
            continue

        content_id = str(
            record.get("content_id")
            or record.get("sample_id")
            or ""
        ).strip()

        if content_id:
            valid_current_content_ids.add(content_id)

    valid_content_ids = (
        set(existing_contents.keys())
        | valid_current_content_ids
    )

    content_snapshots: dict[str, dict] = {}
    comment_snapshots: dict[str, dict] = {}

    content_seen = 0
    comment_seen = 0

    for raw_path, raw in raw_rows:
        record = _normalize_douyin_submission_record(
            raw,
            raw_path.name,
        )

        if not record:
            continue

        is_comment = record.get("record_type") == "comment"

        if not _in_monitoring_time(record, monitoring_start):
            continue

        collection_dt = _collection_time_from_path(raw_path) or now_dt
        collection_text = collection_dt.astimezone(BEIJING).isoformat(
            timespec="seconds"
        )
        collection_bucket = _hour_bucket(collection_dt)

        if is_comment:
            parent_content_id = str(
                record.get("content_id") or ""
            ).strip()

            if parent_content_id not in valid_content_ids:
                continue

            comment_id = str(
                record.get("comment_id")
                or record.get("sample_id")
                or ""
            ).strip()

            if not comment_id:
                continue

            comment_seen += 1

            incoming = {
                "comment_id": comment_id,
                "content_id": parent_content_id,
                "platform": "抖音",
                "comment_user_id": str(record.get("author_id") or ""),
                "comment_user_name": str(record.get("author") or ""),
                "comment_user_ip_location": str(
                    record.get("ip_location")
                    or comment_ip_enrichment.get(
                        comment_id,
                        "",
                    )
                    or ""
                ),
                "comment_text": str(record.get("content") or ""),
                "comment_pictures": str(
                    record.get("pictures")
                    or raw.get("pictures")
                    or ""
                ),
                "comment_publish_time": _beijing_iso(
                    record.get("publish_time")
                ),
                "parent_comment_id": str(
                    record.get("parent_comment_id") or ""
                ),
                "root_comment_id": str(
                    record.get("root_comment_id") or ""
                ),
                "comment_level": int(
                    record.get("comment_level") or 1
                ),
                "is_valid_comment": True,
                "invalid_reason": "",
                "collection_time": collection_text,
            }

            existing_comments[comment_id] = _merge_row(
                existing_comments.get(comment_id, {}),
                incoming,
                "comment_id",
            )

            snap = {
                "content_id": parent_content_id,
                "comment_id": comment_id,
                "platform": "抖音",
                "snapshot_time": collection_text,
                "snapshot_hour": collection_bucket,
                "comment_reply_count": _metric(
                    raw,
                    "sub_comment_count",
                    "sub_comments_count",
                    "reply_count",
                ),
                "comment_like_count": _metric(
                    raw,
                    "like_count",
                    "liked_count",
                    "digg_count",
                    "comment_like_count",
                ),
            }

            snap["snapshot_key"] = (
                f"{parent_content_id}:"
                f"{comment_id}:"
                f"{collection_bucket}"
            )

            comment_snapshots[snap["snapshot_key"]] = snap
            continue

        content_id = str(
            record.get("content_id")
            or record.get("sample_id")
            or ""
        ).strip()

        if not content_id:
            continue

        valid, _ = _topic_decision(
            raw,
            record,
            manual_include,
            manual_exclude,
            require_topic,
        )

        if not valid:
            continue

        content_seen += 1

        matches = set(
            _keyword_list(
                existing_contents.get(
                    content_id,
                    {},
                ).get("matched_keywords")
            )
        )
        matches.update(
            _source_keywords(raw, keywords)
        )

        incoming = {
            "content_id": content_id,
            "platform": "抖音",
            "account_id": str(record.get("author_id") or ""),
            "account_name": str(record.get("author") or ""),
            "account_ip_location": str(record.get("ip_location") or ""),
            "profile_url": str(record.get("author_profile_url") or ""),
            "account_type": str(
                _public_value(
                    raw,
                    "account_type",
                    "user_type",
                    "verification_type",
                )
                or ""
            ),
            "region": str(record.get("ip_location") or ""),
            "organization": str(
                _public_value(
                    raw,
                    "organization",
                    "institution",
                    "enterprise_verify_reason",
                    "custom_verify",
                )
                or ""
            ),
            "title": str(
                _first(
                    raw,
                    "title",
                    "desc",
                    "description",
                    "aweme_desc",
                )
                or record.get("context")
                or ""
            ),
            "content_text": str(record.get("content") or ""),
            "publish_time": _beijing_iso(
                record.get("publish_time")
            ),
            "collection_time": collection_text,
            "original_url": str(record.get("url") or ""),
            "matched_keywords": sorted(matches),
            "original_or_repost": "",
            "is_valid_monitoring_data": True,
            "invalid_reason": "",
        }

        existing_contents[content_id] = _merge_row(
            existing_contents.get(content_id, {}),
            incoming,
            "content_id",
        )

        snap = {
            "content_id": content_id,
            "platform": "抖音",
            "snapshot_time": collection_text,
            "snapshot_hour": collection_bucket,

            # 平台未明确返回时必须为空，不能以0代替缺失。
            "view_count": _metric(
                raw,
                "play_count",
                "view_count",
                "views",
                "video_play_count",
            ),
            "like_count": _metric(
                raw,
                "liked_count",
                "like_count",
                "likes",
                "digg_count",
            ),
            "comment_count": _metric(
                raw,
                "comment_count",
                "comments_count",
                "comments",
            ),

            # 转发与分享严格分开。
            # 当前3130条抖音raw中没有任何独立forward/repost字段。
            "repost_count": _metric(
                raw,
                "forward_count",
                "repost_count",
                "total_forwards",
            ),
            "share_count": _metric(
                raw,
                "share_count",
                "shares",
                "shared_count",
                "video_share_count",
            ),
            "favorite_count": _metric(
                raw,
                "collected_count",
                "favorite_count",
                "favorites",
                "video_favorite_count",
            ),
        }

        snap["snapshot_key"] = (
            f"{content_id}:{collection_bucket}"
        )

        content_snapshots[snap["snapshot_key"]] = snap

    # Table 1 is cumulative valid content.
    final_contents = {
        content_id: row
        for content_id, row in existing_contents.items()
        if content_id not in manual_exclude
    }

    final_valid_ids = set(final_contents)

    # Table 2 is always reverse-filtered by the cleaned Table 1.
    final_comments = {
        comment_id: row
        for comment_id, row in existing_comments.items()
        if str(row.get("content_id") or "") in final_valid_ids
    }

    # Remove orphan nested replies. Repeat until stable.
    while True:
        comment_ids = set(final_comments)
        to_remove = set()

        for comment_id, row in final_comments.items():
            parent_id = str(row.get("parent_comment_id") or "").strip()
            root_id = str(row.get("root_comment_id") or "").strip()

            if (
                parent_id
                and parent_id != comment_id
                and parent_id not in comment_ids
            ):
                to_remove.add(comment_id)
                continue

            if (
                root_id
                and root_id != comment_id
                and root_id not in comment_ids
            ):
                to_remove.add(comment_id)

        if not to_remove:
            break

        for comment_id in to_remove:
            final_comments.pop(comment_id, None)

    _write_rows(
        table1_path,
        [final_contents[key] for key in sorted(final_contents)],
    )

    _write_rows(
        table2_path,
        [final_comments[key] for key in sorted(final_comments)],
    )

    table3_added = _upsert_snapshot_rows(
        table3_path,
        content_snapshots.values(),
    )

    table4_added = _upsert_snapshot_rows(
        table4_path,
        (
            row
            for row in comment_snapshots.values()
            if str(row.get("comment_id") or "") in final_comments
        ),
    )

    table3_rows = _read_rows(table3_path)
    old_accounts = _read_rows(table5_path)

    accounts = _build_accounts(
        list(final_contents.values()),
        table3_rows,
        old_accounts,
        now_text,
    )

    _write_rows(table5_path, accounts)

    manifest = {
        "platform": "douyin",
        "node_id": safe_node,
        "generated_at": now_text,
        "timezone": "Asia/Shanghai (UTC+08:00)",
        "monitoring_start_time": _beijing_iso(monitoring_start),
        "keywords": keywords,
        "table1_content_rows": len(final_contents),
        "table2_comment_rows": len(final_comments),
        "table3_snapshot_rows_total": len(table3_rows),
        "table4_snapshot_rows_total": len(_read_rows(table4_path)),
        "table5_account_rows": len(accounts),
        "content_rows_seen_this_cycle": content_seen,
        "comment_rows_seen_this_cycle": comment_seen,
        "table3_snapshot_rows_added": table3_added,
        "table4_snapshot_rows_added": table4_added,
        "hourly_snapshot_bucket": current_bucket,
        "excluded_reasons_this_cycle": excluded_reasons,
        "table12_update_policy_seconds": 900,
        "table345_update_policy_seconds": 3600,
        "share_semantics": (
            "share_count is exported as share_count; "
            "repost_count remains blank unless the platform "
            "provides an independent forward/repost field."
        ),
    }

    _write_json(manifest_path, manifest)

    return {
        **manifest,
        "output_directory": str(output),
        "files": {
            name: str(output / name)
            for name in TABLES
        },
    }
