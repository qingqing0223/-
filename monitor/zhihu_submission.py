from __future__ import annotations

"""Export Zhihu collection-only data into Tech Design V3 tables 1-5.

Collection scope only: no attitude / issue classification is performed here.
Table 1-2 are refreshed every collection cycle (the Zhihu runner uses 15 minutes).
Table 3-5 are refreshed at most once per wall-clock hour.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable

from pipeline.normalizer import normalize_record


TABLES = {
    "table1_content.jsonl": "content_id",
    "table2_comments.jsonl": "comment_id",
    "table3_content_engagement.jsonl": "snapshot_key",
    "table4_comment_engagement.jsonl": "snapshot_key",
    "table5_accounts.jsonl": "author_id",
}

DEFAULT_KEY_ACCOUNT_CATALOG = "config/key_accounts.v3.catalog.json"


def _read_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _write_rows(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    temp.replace(path)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _parse_time(value: str):
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _normalize_topic_text(value: str) -> str:
    text = str(value or "")
    text = text.translate(str.maketrans({
        "，": ",", "。": ".", "：": ":", "；": ";", "！": "!", "？": "?",
        "—": "-", "–": "-", "－": "-", "　": " ",
    }))
    for ch in (
        " ", "\t", "\r", "\n", ",", ".", ":", ";", "!", "?", "-", "_", "·",
        "“", "”", '"', "'", "（", "）", "(", ")",
    ):
        text = text.replace(ch, "")
    return text


def _matched_keywords(record: dict, keywords: list[str]) -> list[str]:
    visible = "\n".join((str(record.get("content") or ""), str(record.get("context") or "")))
    normalized = _normalize_topic_text(visible)
    return list(dict.fromkeys(
        kw for kw in keywords if _normalize_topic_text(kw) in normalized
    ))


def _in_scope(
    record: dict,
    keywords: list[str],
    monitoring_start_time: str,
    *,
    require_topic: bool = True,
    require_publish_time: bool = True,
) -> tuple[bool, str]:
    published = _parse_time(record.get("publish_time", ""))
    start = _parse_time(monitoring_start_time)
    if require_publish_time and published is None:
        return False, "发布时间缺失或无法解析，无法确认是否属于正式监测时段"
    if published and start:
        if published.tzinfo is None and start.tzinfo is not None:
            published = published.replace(tzinfo=start.tzinfo)
        if published < start:
            return False, "发布时间早于正式监测起点"
    if require_topic and not _matched_keywords(record, keywords):
        return False, "标题/正文未命中完整正式主题关键词"
    return True, ""


def _merge(existing: dict, incoming: dict, key: str) -> dict:
    out = dict(existing)
    for name, value in incoming.items():
        if name not in out or value not in (None, ""):
            out[name] = value
    matches = set(existing.get("matched_keywords") or [])
    matches.update(incoming.get("matched_keywords") or [])
    out["matched_keywords"] = sorted(matches)
    out[key] = str(out.get(key) or incoming.get(key) or "")
    return out


def _public_value(raw: dict, *keys):
    """Return only an explicitly present public value; missing stays blank."""
    for key in keys:
        if key in raw and raw.get(key) not in (None, ""):
            return raw.get(key)
    return ""


def _numeric_public(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value or "").strip().replace(",", "").replace("，", "")
    if not text or any(text.lower().endswith(suffix) for suffix in ("万", "w", "k")):
        return None
    try:
        number = float(text)
        return int(number) if number.is_integer() else None
    except ValueError:
        return None


def _aggregate_if_public(values: list):
    """Aggregate exact numeric public values only; never infer rounded counts."""
    if not values:
        return ""
    parsed = [_numeric_public(v) for v in values]
    if any(v is None for v in parsed):
        return ""
    return sum(parsed)


def _load_key_accounts(repo_root: Path, cfg: dict) -> tuple[dict[str, str], dict[str, str]]:
    catalog_name = str(cfg.get("key_account_catalog") or DEFAULT_KEY_ACCOUNT_CATALOG).strip()
    path = Path(catalog_name)
    if not path.is_absolute():
        path = repo_root / path
    data = _read_json(path)
    aliases: dict[str, str] = {}
    canonical_type: dict[str, str] = {}
    for category in data.get("categories") or []:
        if not isinstance(category, dict):
            continue
        account_type = str(category.get("account_type") or "").strip()
        for name in category.get("accounts") or []:
            canonical = str(name or "").strip()
            if not canonical:
                continue
            canonical_type[canonical] = account_type
            aliases[canonical] = canonical
            for alias in canonical.replace("／", "/").split("/"):
                alias = alias.strip()
                if alias:
                    aliases.setdefault(alias, canonical)
    return aliases, canonical_type


def _account_identity(
    author_name: str,
    aliases: dict[str, str],
    canonical_type: dict[str, str],
) -> tuple[bool, str]:
    canonical = aliases.get(str(author_name or "").strip(), "")
    if not canonical:
        return False, ""
    return True, canonical_type.get(canonical, "")


def _hour_bucket(now_dt: datetime) -> str:
    return now_dt.replace(minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


def _content_id(record: dict) -> str:
    # Prefer the platform ID. sample_id is a stable fallback for URL-only rows.
    return str(record.get("content_id") or record.get("sample_id") or "").strip()


def _upsert_rows(path: Path, incoming: Iterable[dict], key: str) -> int:
    existing = {str(row.get(key) or ""): row for row in _read_rows(path) if row.get(key)}
    before = len(existing)
    for row in incoming:
        row_key = str(row.get(key) or "")
        if row_key:
            existing[row_key] = _merge(existing.get(row_key, {}), row, key)
    _write_rows(path, [existing[k] for k in sorted(existing)])
    return len(existing) - before


def _append_snapshot_rows(path: Path, rows: Iterable[dict]) -> int:
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
    _write_rows(path, [existing[k] for k in sorted(existing)])
    return len(existing) - before


def export_zhihu_submission(
    raw_files: list[Path],
    cfg: dict,
    repo_root: Path,
    node_id: str,
    *,
    now: datetime | None = None,
) -> dict:
    """Merge one Zhihu cycle into data_submissions/zhihu/YYYY-MM-DD_<node>/."""
    now_dt = now or datetime.now(timezone.utc).astimezone()
    if now_dt.tzinfo is None:
        now_dt = now_dt.astimezone()
    now_text = now_dt.isoformat(timespec="seconds")
    date_text = now_dt.date().isoformat()
    safe_node = "".join(
        ch if ch.isalnum() or ch in "-_." else "_"
        for ch in str(node_id or "zhihu01")
    )
    output = repo_root / "data_submissions" / "zhihu" / f"{date_text}_{safe_node}"
    output.mkdir(parents=True, exist_ok=True)

    keywords = [str(x).strip() for x in cfg.get("keywords", []) if str(x).strip()]
    monitoring_start = str(cfg.get("monitoring_start_time") or "")
    require_publish_time = bool(cfg.get("zhihu_require_publish_time", True))
    aliases, canonical_type = _load_key_accounts(repo_root, cfg)

    previous_manifest = _read_json(output / "manifest.json")
    current_bucket = _hour_bucket(now_dt)
    snapshot_due = previous_manifest.get("last_hourly_snapshot_bucket") != current_bucket

    kept = excluded = content_seen = comment_seen = 0
    exclusion_reasons: dict[str, int] = {}
    contents: dict[str, dict] = {}
    comments: dict[str, dict] = {}
    content_snapshots: dict[str, dict] = {}
    comment_snapshots: dict[str, dict] = {}
    account_posts: dict[str, list[tuple[dict, dict]]] = {}
    account_meta: dict[str, dict] = {}

    raw_rows = [(path, raw) for path in raw_files for raw in _read_rows(path)]
    valid_content_ids: set[str] = set()

    # Pass 1 establishes the valid parent set. Replies need not repeat the topic,
    # but their parent content must pass both the time and strict topic checks.
    for raw_path, raw in raw_rows:
        probe = normalize_record(raw, source_file=raw_path.name, platform_hint="zhihu")
        if (
            not probe
            or probe.get("platform") != "zhihu"
            or probe.get("record_type") == "comment"
        ):
            continue
        valid, _ = _in_scope(
            probe,
            keywords,
            monitoring_start,
            require_topic=True,
            require_publish_time=require_publish_time,
        )
        if valid:
            cid = _content_id(probe)
            if cid:
                valid_content_ids.add(cid)

    for raw_path, raw in raw_rows:
        record = normalize_record(raw, source_file=raw_path.name, platform_hint="zhihu")
        if not record or record.get("platform") != "zhihu":
            continue

        is_comment = record.get("record_type") == "comment"
        valid, reason = _in_scope(
            record,
            keywords,
            monitoring_start,
            require_topic=not is_comment,
            require_publish_time=require_publish_time,
        )
        parent_id = str(record.get("content_id") or "").strip()
        if is_comment and parent_id not in valid_content_ids:
            valid, reason = False, "父内容不属于本次正式主题监测范围"
        if not valid:
            excluded += 1
            exclusion_reasons[reason] = exclusion_reasons.get(reason, 0) + 1
            continue

        matches = _matched_keywords(record, keywords) if not is_comment else []
        kept += 1

        if is_comment:
            comment_seen += 1
            comment_id = str(
                record.get("comment_id") or record.get("sample_id") or ""
            ).strip()
            if not comment_id:
                excluded += 1
                reason = "评论ID缺失且无法生成稳定去重键"
                exclusion_reasons[reason] = exclusion_reasons.get(reason, 0) + 1
                continue

            comments[comment_id] = _merge(
                comments.get(comment_id, {}),
                {
                    "content_id": parent_id,
                    "comment_id": comment_id,
                    "platform": "知乎",
                    "comment_user_id": str(record.get("author_id") or ""),
                    "comment_user_ip_location": str(record.get("ip_location") or ""),
                    "comment_text": record.get("content", ""),
                    "comment_publish_time": record.get("publish_time", ""),
                    "parent_comment_id": str(record.get("parent_comment_id") or ""),
                    "root_comment_id": str(record.get("root_comment_id") or ""),
                    "comment_level": record.get("comment_level", 1),
                    "is_valid_comment": True,
                    "invalid_reason": "",
                    "collection_time": now_text,
                },
                "comment_id",
            )
            if snapshot_due:
                snap = {
                    "content_id": parent_id,
                    "comment_id": comment_id,
                    "platform": "知乎",
                    "snapshot_time": now_text,
                    "comment_reply_count": _public_value(
                        raw, "sub_comment_count", "reply_count"
                    ),
                    "comment_like_count": _public_value(
                        raw, "like_count", "liked_count", "voteup_count"
                    ),
                }
                snap["snapshot_key"] = f"{parent_id}:{comment_id}:{current_bucket}"
                comment_snapshots[comment_id] = snap
            continue

        content_seen += 1
        content_id = _content_id(record)
        if not content_id:
            excluded += 1
            reason = "发布内容ID/稳定去重键缺失"
            exclusion_reasons[reason] = exclusion_reasons.get(reason, 0) + 1
            continue

        author_name = str(record.get("author") or "")
        is_key, account_type = _account_identity(
            author_name, aliases, canonical_type
        )
        source_keyword = str(record.get("source_keyword") or "").strip()
        if source_keyword in keywords and source_keyword not in matches:
            # Provenance only: source_keyword never bypasses the visible-text check.
            matches = [*matches, source_keyword]

        contents[content_id] = _merge(
            contents.get(content_id, {}),
            {
                "content_id": content_id,
                "platform": "知乎",
                "author_id": str(record.get("author_id") or ""),
                "author_name": author_name,
                "author_ip_location": str(record.get("ip_location") or ""),
                "account_type": account_type,
                "content_type": str(
                    raw.get("content_type") or record.get("record_type") or ""
                ),
                "title": str(raw.get("title") or record.get("context") or ""),
                "content_text": record.get("content", ""),
                "publish_time": record.get("publish_time", ""),
                "collection_time": now_text,
                "original_url": record.get("url", ""),
                "matched_keywords": matches,
                "original_or_repost": "",
                "is_valid_monitoring_data": True,
                "invalid_reason": "",
            },
            "content_id",
        )

        if snapshot_due:
            snap = {
                "content_id": content_id,
                "platform": "知乎",
                "snapshot_time": now_text,
                "view_count": _public_value(raw, "view_count", "views"),
                "like_count": _public_value(
                    raw, "voteup_count", "like_count", "likes"
                ),
                "comment_count": _public_value(
                    raw, "comment_count", "comments_count", "comments"
                ),
                "repost_count": _public_value(raw, "repost_count", "forward_count"),
                "share_count": _public_value(raw, "share_count", "shares"),
                "favorite_count": _public_value(
                    raw, "favorite_count", "favorites", "collected_count"
                ),
            }
            snap["snapshot_key"] = f"{content_id}:{current_bucket}"
            content_snapshots[content_id] = snap

        author_id = str(record.get("author_id") or "").strip()
        if snapshot_due and author_id:
            account_posts.setdefault(author_id, []).append((record, raw))
            meta = account_meta.setdefault(
                author_id,
                {
                    "author_id": author_id,
                    "platform": "知乎",
                    "author_name": author_name,
                    "profile_url": str(record.get("author_profile_url") or ""),
                    "account_type": account_type,
                    "fan_count": _public_value(
                        raw,
                        "fans_count",
                        "followers_count",
                        "follower_count",
                        "followers",
                    ),
                    "following_count": _public_value(
                        raw, "following_count", "follow_count", "following"
                    ),
                    "region": str(record.get("ip_location") or ""),
                    "organization": "",
                    "is_key_account": is_key,
                },
            )
            for field, value in (
                ("author_name", author_name),
                ("profile_url", str(record.get("author_profile_url") or "")),
                ("account_type", account_type),
                ("region", str(record.get("ip_location") or "")),
            ):
                if value:
                    meta[field] = value
            if is_key:
                meta["is_key_account"] = True

    new_table1 = _upsert_rows(
        output / "table1_content.jsonl", contents.values(), "content_id"
    )
    new_table2 = _upsert_rows(
        output / "table2_comments.jsonl", comments.values(), "comment_id"
    )

    table3_added = table4_added = table5_changed = 0
    if snapshot_due:
        table3_added = _append_snapshot_rows(
            output / "table3_content_engagement.jsonl",
            content_snapshots.values(),
        )
        table4_added = _append_snapshot_rows(
            output / "table4_comment_engagement.jsonl",
            comment_snapshots.values(),
        )

        account_rows: list[dict] = []
        for author_id, post_pairs in account_posts.items():
            meta = dict(account_meta[author_id])
            raw_posts = [raw for _, raw in post_pairs]
            account_row = {
                **meta,
                "related_post_count": len(
                    {_content_id(rec) for rec, _ in post_pairs if _content_id(rec)}
                ),
                "view_count": _aggregate_if_public([
                    _public_value(raw, "view_count", "views") for raw in raw_posts
                ]),
                "like_count": _aggregate_if_public([
                    _public_value(raw, "voteup_count", "like_count", "likes")
                    for raw in raw_posts
                ]),
                "comment_count": _aggregate_if_public([
                    _public_value(raw, "comment_count", "comments_count", "comments")
                    for raw in raw_posts
                ]),
                "repost_count": _aggregate_if_public([
                    _public_value(raw, "repost_count", "forward_count")
                    for raw in raw_posts
                ]),
                "favorite_count": _aggregate_if_public([
                    _public_value(raw, "favorite_count", "favorites", "collected_count")
                    for raw in raw_posts
                ]),
                "total_engagement": "",
                "collection_time": now_text,
            }
            interaction_parts = [
                account_row["like_count"],
                account_row["comment_count"],
                account_row["repost_count"],
                account_row["favorite_count"],
            ]
            if all(value != "" for value in interaction_parts):
                account_row["total_engagement"] = sum(
                    int(value) for value in interaction_parts
                )
            account_rows.append(account_row)
        table5_changed = _upsert_rows(
            output / "table5_accounts.jsonl", account_rows, "author_id"
        )

    # Always leave a complete five-file submission package, even after a zero-hit cycle.
    for filename in TABLES:
        path = output / filename
        if not path.exists():
            _write_rows(path, [])

    manifest = {
        "platform": "zhihu",
        "node_id": safe_node,
        "generated_at": now_text,
        "monitoring_start_time": monitoring_start,
        "keywords": keywords,
        "accepted_rows": kept,
        "excluded_rows": excluded,
        "exclusion_reasons": exclusion_reasons,
        "content_rows_seen_this_cycle": content_seen,
        "comment_rows_seen_this_cycle": comment_seen,
        "table1_new_rows": new_table1,
        "table2_new_rows": new_table2,
        "hourly_snapshot_due": snapshot_due,
        "hourly_snapshot_bucket": (
            current_bucket
            if snapshot_due
            else previous_manifest.get("last_hourly_snapshot_bucket", "")
        ),
        "table3_snapshot_rows_added": table3_added,
        "table4_snapshot_rows_added": table4_added,
        "table5_accounts_changed": table5_changed,
        "last_hourly_snapshot_bucket": (
            current_bucket
            if snapshot_due
            else previous_manifest.get("last_hourly_snapshot_bucket", "")
        ),
        "table12_update_policy_seconds": 900,
        "table345_update_policy_seconds": 3600,
        "classification": "not_run_collection_group_scope_only",
        "output_directory_contract": (
            "data_submissions/zhihu/YYYY-MM-DD_<node_id>/"
        ),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {**manifest, "output_dir": str(output)}