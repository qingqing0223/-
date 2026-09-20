from __future__ import annotations
from datetime import datetime, timedelta, timezone
import json
import re
from pathlib import Path
from pipeline.io_utils import read_jsonl, append_jsonl, read_json, write_json
from pipeline.normalizer import normalize_record
from pipeline.classifier import classify_records
from pipeline.language_detector import is_minority_language
from .kuaishou_key_accounts import (
    enrich_kuaishou_key_account_records,
    load_kuaishou_key_accounts,
)


COUNTRY_ONLY_REGION_LABELS = {"中国", "中国大陆", "中华人民共和国", "China", "Mainland China", "PRC", "CN"}
BEIJING_TZ = timezone(timedelta(hours=8))

PROVINCE_ALIASES = [
    ("内蒙古", "内蒙古"), ("广西", "广西"), ("西藏", "西藏"), ("宁夏", "宁夏"), ("新疆", "新疆"),
    ("香港", "香港"), ("澳门", "澳门"),
    ("北京", "北京"), ("天津", "天津"), ("上海", "上海"), ("重庆", "重庆"),
    ("河北", "河北"), ("山西", "山西"), ("辽宁", "辽宁"), ("吉林", "吉林"), ("黑龙江", "黑龙江"),
    ("江苏", "江苏"), ("浙江", "浙江"), ("安徽", "安徽"), ("福建", "福建"), ("江西", "江西"),
    ("山东", "山东"), ("河南", "河南"), ("湖北", "湖北"), ("湖南", "湖南"), ("广东", "广东"),
    ("海南", "海南"), ("四川", "四川"), ("贵州", "贵州"), ("云南", "云南"), ("陕西", "陕西"),
    ("甘肃", "甘肃"), ("青海", "青海"), ("台湾", "台湾"),
]


def _canonical_public_region(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    for prefix in ("IP属地：", "IP属地:", "IP属地", "来自：", "来自:", "来自"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    if text in COUNTRY_ONLY_REGION_LABELS or re.fullmatch(r"[A-Za-z]{2,3}", text):
        return ""
    for needle, province in PROVINCE_ALIASES:
        if needle in text:
            return province
    if len(text) <= 16 and not any(ch.isdigit() for ch in text):
        return text
    return ""


def _prepare_region_aliases(raw: dict) -> dict:
    if not isinstance(raw, dict):
        return raw
    out = dict(raw)
    candidates = [
        raw.get("ip_location"), raw.get("ip_region"), raw.get("ip_label"),
        raw.get("province"), raw.get("province_name"), raw.get("user_province"),
        raw.get("author_province"), raw.get("region"), raw.get("region_name"),
        raw.get("comment_ip_location"), raw.get("user_ip_location"),
    ]
    for parent_key in ("user", "user_info", "author", "creator", "member"):
        parent = raw.get(parent_key)
        if isinstance(parent, dict):
            candidates.extend([
                parent.get("ip_location"), parent.get("ip_region"), parent.get("ip_label"),
                parent.get("ip_address"), parent.get("province"), parent.get("province_name"), parent.get("region"),
            ])
    reply_control = raw.get("reply_control")
    if isinstance(reply_control, dict):
        candidates.append(reply_control.get("location"))
    for value in candidates:
        region = _canonical_public_region(value)
        if region:
            out["ip_location"] = region
            break
    return out


def _parse_iso_datetime(value, default_tz=None):
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        return None
    if dt.tzinfo is None and default_tz is not None:
        dt = dt.replace(tzinfo=default_tz)
    return dt


def _before_monitoring_start(rec: dict, monitoring_start_time: str) -> bool:
    start = _parse_iso_datetime(monitoring_start_time)
    if start is None:
        return False
    published = _parse_iso_datetime(rec.get("publish_time"), default_tz=start.tzinfo)
    if published is None:
        return False
    return published < start


def _time_scope_reason(rec: dict, monitoring_start_time: str, monitoring_end_time: str = "") -> str:
    """Return why a record is outside the formal Beijing-time monitoring scope."""
    start = _parse_iso_datetime(monitoring_start_time, default_tz=BEIJING_TZ)
    if start is None:
        return "invalid_monitoring_start"
    published_text = str(rec.get("publish_time") or "").strip()
    if not published_text:
        return "missing_publish_time"
    published = _parse_iso_datetime(published_text, default_tz=start.tzinfo)
    if published is None:
        return "unparseable_publish_time"
    if published < start:
        return "before_monitoring_start"
    end = _parse_iso_datetime(monitoring_end_time, default_tz=start.tzinfo)
    if end is not None and published >= end:
        return "at_or_after_monitoring_end"
    return ""


def _snapshot_due(last_observed: str, observed_at: str, interval_seconds: int) -> bool:
    last = _parse_iso_datetime(last_observed)
    current = _parse_iso_datetime(observed_at)
    if last is None or current is None:
        return True
    return (current - last).total_seconds() >= interval_seconds


def _append_kuaishou_engagement_snapshots(
    records: list[dict], state_path: Path, output_path: Path,
    interval_seconds: int, observed_at: str,
) -> dict:
    state = read_json(state_path, {"last_observed": {}})
    last_observed = state.setdefault("last_observed", {})
    snapshots = []
    skipped_not_due = 0
    skipped_missing_id = 0
    for rec in records:
        record_type = str(rec.get("record_type") or "")
        if record_type == "comment":
            if not rec.get("is_key_monitor_comment", False):
                continue
            entity_id = str(rec.get("comment_id") or "").strip()
            entity_type = "comment"
            metrics = {
                "like_count": rec.get("likes"),
                "reply_count": rec.get("comment_reply_count"),
            }
        else:
            if not rec.get("is_key_monitor_content", False):
                continue
            entity_id = str(rec.get("content_id") or rec.get("url") or "").strip()
            entity_type = "content"
            metrics = {
                "view_or_play_count": rec.get("views"),
                "like_count": rec.get("likes"),
                "comment_count": rec.get("comments"),
                "repost_count": rec.get("reposts"),
                "share_count": rec.get("shares"),
                "favorite_count": rec.get("favorites"),
            }
        if not entity_id:
            skipped_missing_id += 1
            continue
        state_key = f"{entity_type}:{entity_id}"
        if not _snapshot_due(str(last_observed.get(state_key) or ""), observed_at, interval_seconds):
            skipped_not_due += 1
            continue
        missing = {
            name: "field_missing_or_unparseable"
            for name, value in metrics.items() if value is None
        }
        snapshots.append({
            "platform": "ks",
            "entity_type": entity_type,
            "content_id": str(rec.get("content_id") or ""),
            "comment_id": str(rec.get("comment_id") or ""),
            "url": str(rec.get("url") or ""),
            "is_key_monitor_content": bool(rec.get("is_key_monitor_content", False)),
            "is_key_monitor_comment": bool(rec.get("is_key_monitor_comment", False)),
            "statistics_time": observed_at,
            "metrics": metrics,
            "missing_reasons": missing,
        })
        last_observed[state_key] = observed_at
    if snapshots:
        append_jsonl(output_path, snapshots)
        write_json(state_path, state)
    return {
        "snapshot_records": len(snapshots),
        "snapshot_skipped_not_due": skipped_not_due,
        "snapshot_skipped_missing_id": skipped_missing_id,
        "snapshot_output": str(output_path),
        "snapshot_interval_seconds": interval_seconds,
    }


def _complete_metric_sum(content_rows: dict, field: str):
    values = [row.get(field) for row in content_rows.values()]
    if not values or any(value is None for value in values):
        return None
    return sum(int(value) for value in values)


def _update_kuaishou_account_snapshots(
    records: list[dict], state_path: Path, output_path: Path,
    interval_seconds: int, observed_at: str,
) -> dict:
    state = read_json(state_path, {"accounts": {}})
    accounts = state.setdefault("accounts", {})
    skipped_without_stable_id = 0
    for rec in records:
        if rec.get("record_type") == "comment":
            continue
        account_id = str(rec.get("author_id") or "").strip()
        if not account_id:
            skipped_without_stable_id += 1
            continue
        account = accounts.setdefault(account_id, {"contents": {}, "last_snapshot_at": ""})
        for target, source in (
            ("account_name", "author"), ("profile_url", "author_profile_url"),
            ("account_region", "account_region"), ("account_type", "account_type"),
            ("institution", "institution"), ("follower_count", "follower_count"),
            ("following_count", "following_count"),
        ):
            value = rec.get(source)
            if value not in (None, ""):
                account[target] = value
        if rec.get("is_key_monitor_account") and rec.get("key_account_category"):
            account["account_type"] = rec["key_account_category"]
        if rec.get("is_key_monitor_account") and rec.get("key_account_institution"):
            account["institution"] = rec["key_account_institution"]
        account["is_key_monitor_account"] = bool(rec.get("is_key_monitor_account", False))
        account["key_account_match_basis"] = str(rec.get("key_account_match_basis") or "none")
        account["key_account_match_status"] = str(rec.get("key_account_match_status") or "no_match")
        content_id = str(rec.get("content_id") or rec.get("url") or "").strip()
        if content_id:
            account["contents"][content_id] = {
                "views": rec.get("views"), "likes": rec.get("likes"),
                "comments": rec.get("comments"), "reposts": rec.get("reposts"),
                "favorites": rec.get("favorites"),
            }

    snapshots = []
    for account_id, account in accounts.items():
        if not _snapshot_due(str(account.get("last_snapshot_at") or ""), observed_at, interval_seconds):
            continue
        contents = account.get("contents") or {}
        aggregates = {
            "related_post_count": len(contents),
            "view_or_play_count": _complete_metric_sum(contents, "views"),
            "like_count": _complete_metric_sum(contents, "likes"),
            "comment_count": _complete_metric_sum(contents, "comments"),
            "repost_count": _complete_metric_sum(contents, "reposts"),
            "favorite_count": _complete_metric_sum(contents, "favorites"),
        }
        interaction_fields = ("like_count", "comment_count", "repost_count", "favorite_count")
        aggregates["total_interaction_count"] = (
            sum(int(aggregates[field]) for field in interaction_fields)
            if all(aggregates[field] is not None for field in interaction_fields) else None
        )
        missing = {
            field: "not_collected_or_incomplete_across_related_posts"
            for field, value in aggregates.items() if value is None
        }
        snapshots.append({
            "account_attributes": {
                "account_id": account_id,
                "platform": "ks",
                "account_name": account.get("account_name") or None,
                "profile_url": account.get("profile_url") or None,
                "account_type": account.get("account_type") or None,
                "follower_count": account.get("follower_count"),
                "following_count": account.get("following_count"),
                "account_region": account.get("account_region") or None,
                "institution": account.get("institution") or None,
                "is_key_monitor_account": bool(account.get("is_key_monitor_account", False)),
                "key_account_match_basis": account.get("key_account_match_basis") or "none",
                "key_account_match_status": account.get("key_account_match_status") or "no_match",
            },
            "monitoring_period_aggregates": aggregates,
            "data_collection_time": observed_at,
            "missing_reasons": missing,
        })
        account["last_snapshot_at"] = observed_at
    if snapshots:
        append_jsonl(output_path, snapshots)
    write_json(state_path, state)
    return {
        "account_snapshot_records": len(snapshots),
        "account_snapshot_interval_seconds": interval_seconds,
        "account_snapshot_output": str(output_path),
        "accounts_without_stable_id": skipped_without_stable_id,
    }


def load_seen(path: Path) -> set[str]:
    data = read_json(path, {"seen": []})
    return set(map(str, data.get("seen", [])))


def save_seen(path: Path, seen: set[str]) -> None:
    write_json(path, {"seen": sorted(seen)})


def _merge_regions_into_existing(output_jsonl: Path, region_by_key: dict[str, str]) -> int:
    if not region_by_key or not output_jsonl.exists():
        return 0
    rows = list(read_jsonl(output_jsonl))
    updated = 0
    for row in rows:
        key = str(row.get("dedupe_key") or "").strip()
        region = region_by_key.get(key, "")
        if not key or not region:
            continue
        old = str(row.get("ip_location") or "").strip()
        if old:
            continue
        row["ip_location"] = region
        updated += 1
    if not updated:
        return 0

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_jsonl.with_suffix(output_jsonl.suffix + ".region.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(output_jsonl)
    return updated


def ingest_and_classify(platform: str, jsonl_files: list[Path], state_path: Path,
                        output_jsonl: Path, concurrency: int = 4,
                        monitoring_start_time: str = "", monitoring_end_time: str = "",
                        engagement_snapshot_interval_seconds: int = 3600,
                        account_snapshot_interval_seconds: int = 86400,
                        key_accounts_config_path: str = "",
                        observed_at: str = "") -> dict:
    seen = load_seen(state_path)
    fresh = []
    filtered_before_start = 0
    filtered_before_start_comment_records = 0
    filtered_before_start_content_records = 0
    filtered_at_or_after_end = 0
    filtered_missing_publish_time = 0
    filtered_unparseable_publish_time = 0
    region_by_key: dict[str, str] = {}
    snapshot_candidates: list[dict] = []

    raw_rows = 0
    raw_comment_rows = 0
    normalized_records = 0
    normalized_comment_records = 0
    normalization_dropped = 0
    duplicate_skipped = 0
    duplicate_comment_skipped = 0
    duplicate_content_skipped = 0

    for path in jsonl_files:
        is_comment_file = "comment" in path.name.lower()
        for raw in read_jsonl(path):
            raw_rows += 1
            if is_comment_file:
                raw_comment_rows += 1
            raw = _prepare_region_aliases(raw)
            rec = normalize_record(raw, source_file=path.name, platform_hint=platform)
            if not rec:
                normalization_dropped += 1
                continue
            normalized_records += 1
            if rec.get("record_type") == "comment":
                normalized_comment_records += 1
            if platform == "ks":
                scope_reason = _time_scope_reason(rec, monitoring_start_time, monitoring_end_time)
                if scope_reason:
                    if scope_reason == "before_monitoring_start":
                        filtered_before_start += 1
                        if rec.get("record_type") == "comment":
                            filtered_before_start_comment_records += 1
                        else:
                            filtered_before_start_content_records += 1
                    elif scope_reason == "at_or_after_monitoring_end":
                        filtered_at_or_after_end += 1
                    elif scope_reason == "missing_publish_time":
                        filtered_missing_publish_time += 1
                    else:
                        filtered_unparseable_publish_time += 1
                    continue
            if platform == "ks":
                snapshot_candidates.append(rec)
            key = rec["dedupe_key"]
            region = _canonical_public_region(rec.get("ip_location"))
            if region:
                region_by_key[key] = region
            if key in seen:
                duplicate_skipped += 1
                if rec.get("record_type") == "comment":
                    duplicate_comment_skipped += 1
                else:
                    duplicate_content_skipped += 1
                continue
            seen.add(key)
            if _before_monitoring_start(rec, monitoring_start_time):
                filtered_before_start += 1
                if rec.get("record_type") == "comment":
                    filtered_before_start_comment_records += 1
                else:
                    filtered_before_start_content_records += 1
                continue
            if region:
                rec["ip_location"] = region
            fresh.append(rec)

    snapshot_summary = {}
    key_account_summary = {}
    account_snapshot_summary = {}
    if platform == "ks":
        snapshot_time = observed_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        registry_path = Path(key_accounts_config_path) if key_accounts_config_path else Path()
        registry = load_kuaishou_key_accounts(registry_path) if key_accounts_config_path else {
            "platform": "ks", "accounts": [], "key_content_ids": []
        }
        key_account_summary = enrich_kuaishou_key_account_records(
            snapshot_candidates,
            registry,
            state_path.parent / "kuaishou_key_content_ids.json",
        )
        snapshot_summary = _append_kuaishou_engagement_snapshots(
            snapshot_candidates,
            state_path.parent / "kuaishou_engagement_snapshot_state.json",
            output_jsonl.parent / "kuaishou_engagement_snapshots.jsonl",
            max(3600, int(engagement_snapshot_interval_seconds)),
            snapshot_time,
        )
        account_snapshot_summary = _update_kuaishou_account_snapshots(
            snapshot_candidates,
            state_path.parent / "kuaishou_account_snapshot_state.json",
            output_jsonl.parent / "kuaishou_account_snapshots.jsonl",
            max(86400, int(account_snapshot_interval_seconds)),
            snapshot_time,
        )

    region_backfilled_records = _merge_regions_into_existing(output_jsonl, region_by_key)

    classified = classify_records(fresh, concurrency=concurrency)
    append_jsonl(output_jsonl, classified)
    save_seen(state_path, seen)

    region_records = sum(1 for row in classified if str(row.get("ip_location") or "").strip())
    language_counts: dict[str, int] = {}
    minority_language_records = 0
    for row in classified:
        language = str(row.get("language") or "未知").strip() or "未知"
        language_counts[language] = language_counts.get(language, 0) + 1
        if is_minority_language(language):
            minority_language_records += 1

    total = len(classified)
    classified_comment_records = sum(1 for row in classified if row.get("record_type") == "comment")
    classification_degraded_records = sum(1 for row in classified if row.get("classification_ok") is False)
    classification_degraded_comment_records = sum(
        1 for row in classified
        if row.get("record_type") == "comment" and row.get("classification_ok") is False
    )
    classification_errors = sorted({
        str(row.get("classification_error") or "").strip()
        for row in classified
        if row.get("classification_ok") is False and str(row.get("classification_error") or "").strip()
    })

    return {
        "platform": platform,
        "monitoring_start_time": monitoring_start_time,
        "monitoring_end_time": monitoring_end_time,
        "input_files": [str(p) for p in jsonl_files],
        "raw_rows": raw_rows,
        "raw_comment_rows": raw_comment_rows,
        "normalized_records": normalized_records,
        "normalized_comment_records": normalized_comment_records,
        "normalization_dropped": normalization_dropped,
        "duplicate_skipped": duplicate_skipped,
        "new_records": len(fresh),
        "filtered_before_start": filtered_before_start,
        "filtered_before_start_comment_records": filtered_before_start_comment_records,
        "filtered_before_start_content_records": filtered_before_start_content_records,
        "filtered_at_or_after_end": filtered_at_or_after_end,
        "filtered_missing_publish_time": filtered_missing_publish_time,
        "filtered_unparseable_publish_time": filtered_unparseable_publish_time,
        "duplicate_comment_skipped": duplicate_comment_skipped,
        "duplicate_content_skipped": duplicate_content_skipped,
        "classified_records": total,
        "classified_comment_records": classified_comment_records,
        "classification_degraded_records": classification_degraded_records,
        "classification_degraded_comment_records": classification_degraded_comment_records,
        "classification_degraded": classification_degraded_records > 0,
        "classification_errors": classification_errors[:3],
        "region_records": region_records,
        "region_rate": round(region_records / total, 4) if total else 0.0,
        "region_backfilled_records": region_backfilled_records,
        "minority_language_records": minority_language_records,
        "minority_language_rate": round(minority_language_records / total, 4) if total else 0.0,
        "language_counts": dict(sorted(language_counts.items(), key=lambda item: (-item[1], item[0]))),
        "total_seen": len(seen),
        "engagement_snapshots": snapshot_summary,
        "key_accounts": key_account_summary,
        "account_snapshots": account_snapshot_summary,
        "_classified_rows": classified,
    }
