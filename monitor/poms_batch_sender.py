from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import urllib.error
import urllib.request
from typing import Any


TABLE_FILES = {
    "table1": "table1_content.jsonl",
    "table2": "table2_comments.jsonl",
    "table3": "table3_post_interactions.jsonl",
    "table4": "table4_comment_interactions.jsonl",
    "table5": "table5_accounts.jsonl",
}

TABLE_ENDPOINTS = {
    "table1": "published_content_basic_information",
    "table2": "comment_basic_information",
    "table3": "published_content_interaction_data",
    "table4": "comment_content_interaction_data",
    "table5": "account_information",
}

TABLE12_GROUP = "table1_table2"
TABLE345_GROUP = "table3_table4_table5"
DEFAULT_BATCH_SIZE = 50


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _nullable_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _metric(value: Any) -> int:
    if value in (None, "") or isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return 0
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return 0


def _keywords(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = _text(value)
    return [text] if text else []


def _content_type(value: Any) -> str:
    text = _text(value)
    mapping = {
        "post": "图文",
        "article": "图文",
        "text": "图文",
        "video": "视频",
    }
    return mapping.get(text.lower(), text)


def build_poms_record(table_key: str, row: dict) -> dict:
    """Map one local Tech Design V3 row to the exact POMS batch schema.

    Local exports keep unavailable public metrics blank. POMS requires numeric
    statistical fields to be present, so blanks are converted to 0 only in the
    outbound API payload; the local source JSONL is never rewritten.
    """
    if table_key == "table1":
        return {
            "published_content_id": _text(row.get("content_id")),
            "platform_name": _text(row.get("platform")),
            "publisher_account_id": _text(row.get("author_id")),
            "account_name": _text(row.get("author_name")),
            "account_ip_location": _nullable_text(row.get("author_ip_location")),
            "account_type": _nullable_text(row.get("account_type")),
            "content_type": _content_type(row.get("content_type")),
            "title": _text(row.get("title")),
            "body_text_or_video_description": _text(row.get("content_text")),
            "published_at": _text(row.get("publish_time")),
            "collected_at": _text(row.get("collection_time")),
            "original_content_url": _text(row.get("original_url")),
            "matched_keywords": _keywords(row.get("matched_keywords")),
            "originality_status": _text(row.get("original_or_repost")),
            "is_valid_monitoring_data": bool(row.get("is_valid_monitoring_data")),
            "invalid_reason": _nullable_text(row.get("invalid_reason")),
        }

    if table_key == "table2":
        return {
            "corresponding_published_content_id": _text(row.get("content_id")),
            "comment_id": _text(row.get("comment_id")),
            "platform_name": _text(row.get("platform")),
            "commenter_user_id": _text(row.get("comment_user_id")),
            "commenter_ip_location": _nullable_text(row.get("comment_user_ip_location")),
            "comment_text": _text(row.get("comment_text")),
            "commented_at": _text(row.get("comment_publish_time")),
            "is_valid_comment": bool(row.get("is_valid_comment")),
        }

    if table_key == "table3":
        return {
            "corresponding_published_content_id": _text(row.get("content_id")),
            "platform_name": _text(row.get("platform")),
            "statistical_time": _text(row.get("snapshot_time")),
            "view_or_play_count": _metric(row.get("view_count")),
            "like_count": _metric(row.get("like_count")),
            "comment_count": _metric(row.get("comment_count")),
            "repost_count": _metric(row.get("repost_count")),
            "share_count": _metric(row.get("share_count")),
            "favorite_count": _metric(row.get("favorite_count")),
        }

    if table_key == "table4":
        return {
            "corresponding_published_content_id": _text(row.get("content_id")),
            "comment_id": _text(row.get("comment_id")),
            "platform_name": _text(row.get("platform")),
            "statistical_time": _text(row.get("snapshot_time")),
            "comment_reply_count": _metric(row.get("comment_reply_count")),
            "comment_like_count": _metric(row.get("comment_like_count")),
        }

    if table_key == "table5":
        return {
            "account_id": _text(row.get("account_id")),
            "platform": _text(row.get("platform")),
            "account_name": _text(row.get("account_name")),
            "homepage_url": _text(row.get("profile_url")),
            "account_type": _nullable_text(row.get("account_type")),
            "follower_count": _metric(row.get("followers")),
            "following_count": _metric(row.get("following")),
            "region": _nullable_text(row.get("region")),
            "organization": _nullable_text(row.get("organization")),
            "is_key_monitored_account": bool(row.get("is_key_account")),
            "related_post_count": _metric(row.get("related_post_count")),
            "view_or_play_count": _metric(row.get("views")),
            "like_count": _metric(row.get("likes")),
            "comment_count": _metric(row.get("comments")),
            "repost_count": _metric(row.get("shares")),
            "favorite_count": _metric(row.get("favorites")),
            "total_interaction_count": _metric(row.get("total_interactions")),
            "collected_at": _text(row.get("collected_at")),
        }

    raise ValueError(f"unsupported POMS table key: {table_key}")


def build_poms_payload(table_key: str, rows: list[dict]) -> list[dict]:
    return [build_poms_record(table_key, row) for row in rows]


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
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


def _write_events(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        if path.exists():
            path.unlink()
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def _event_id(event: dict) -> str:
    existing = _text(event.get("event_id"))
    if existing:
        return existing
    groups = "+".join(str(x) for x in (event.get("published_groups") or []))
    return ":".join([
        _text(event.get("platform")) or "wb",
        _text(event.get("node_id")) or "wb01",
        _text(event.get("published_at")),
        groups,
    ])


def _safe_event_name(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return text.strip("-.") or "event"


def _tables_for_event(event: dict) -> list[str]:
    groups = set(str(x) for x in (event.get("published_groups") or []))
    out = []
    if TABLE12_GROUP in groups:
        out.extend(["table1", "table2"])
    if TABLE345_GROUP in groups:
        out.extend(["table3", "table4", "table5"])
    return out


def _snapshot_event(event: dict, payload_root: Path) -> dict:
    snapshot = dict(event)
    event_id = _event_id(snapshot)
    snapshot["event_id"] = event_id
    event_dir = payload_root / _safe_event_name(event_id)
    event_dir.mkdir(parents=True, exist_ok=True)

    source_files = dict(event.get("table_files") or {})
    copied = dict(source_files)
    for table_key in _tables_for_event(event):
        source_text = _text(source_files.get(table_key))
        if not source_text:
            continue
        source = Path(source_text)
        if not source.exists():
            continue
        target = event_dir / TABLE_FILES[table_key]
        if not target.exists():
            shutil.copy2(source, target)
        copied[table_key] = str(target)

    snapshot["table_files"] = copied
    snapshot["poms_payload_snapshot_dir"] = str(event_dir)
    return snapshot


def _cleanup_snapshot(event: dict) -> None:
    path_text = _text(event.get("poms_payload_snapshot_dir"))
    if not path_text:
        return
    path = Path(path_text)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def post_batch(
    base_url: str,
    api_key: str,
    table_key: str,
    payload: list[dict],
    *,
    timeout_seconds: int = 20,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict:
    if table_key not in TABLE_ENDPOINTS:
        return {"ok": False, "table": table_key, "error": "unsupported_table"}
    if not payload:
        return {
            "ok": True,
            "table": table_key,
            "sent": 0,
            "batches": 0,
            "skipped_empty": True,
        }

    batch_size = max(1, int(batch_size or DEFAULT_BATCH_SIZE))
    url = (
        f"{base_url.rstrip('/')}/api/v1/tables/"
        f"{TABLE_ENDPOINTS[table_key]}/batch"
    )
    sent = 0
    batch_count = 0

    for start in range(0, len(payload), batch_size):
        chunk = payload[start:start + batch_size]
        body = json.dumps(
            chunk,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "X-API-Key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout_seconds,
            ) as response:
                raw = response.read().decode("utf-8", errors="replace")
                status = int(getattr(response, "status", 200))
                if status < 200 or status >= 300:
                    return {
                        "ok": False,
                        "table": table_key,
                        "http_status": status,
                        "sent": sent,
                        "error": raw,
                    }
                if raw:
                    try:
                        decoded = json.loads(raw)
                    except json.JSONDecodeError:
                        return {
                            "ok": False,
                            "table": table_key,
                            "http_status": status,
                            "sent": sent,
                            "error": "non_json_response",
                        }
                    if not isinstance(decoded, list):
                        return {
                            "ok": False,
                            "table": table_key,
                            "http_status": status,
                            "sent": sent,
                            "error": "non_list_response",
                        }
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return {
                "ok": False,
                "table": table_key,
                "http_status": exc.code,
                "sent": sent,
                "error": detail or str(exc),
            }
        except Exception as exc:
            return {
                "ok": False,
                "table": table_key,
                "sent": sent,
                "error": f"{type(exc).__name__}: {exc}",
            }

        sent += len(chunk)
        batch_count += 1

    return {
        "ok": True,
        "table": table_key,
        "sent": sent,
        "batches": batch_count,
        "http_status": 200,
    }


def deliver_publication_event(
    event: dict,
    base_url: str,
    api_key: str,
    *,
    timeout_seconds: int = 20,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict:
    table_files = dict(event.get("table_files") or {})
    completed = []
    results = []

    for table_key in _tables_for_event(event):
        path_text = _text(table_files.get(table_key))
        if not path_text:
            return {
                "ok": False,
                "event_id": _event_id(event),
                "failed_table": table_key,
                "completed_tables": completed,
                "error": "missing_table_file",
            }
        rows = _read_jsonl(Path(path_text))
        payload = build_poms_payload(table_key, rows)
        result = post_batch(
            base_url,
            api_key,
            table_key,
            payload,
            timeout_seconds=timeout_seconds,
            batch_size=batch_size,
        )
        results.append(result)
        if not result.get("ok"):
            return {
                "ok": False,
                "event_id": _event_id(event),
                "failed_table": table_key,
                "completed_tables": completed,
                "table_results": results,
                "error": result.get("error", "poms_batch_failed"),
            }
        completed.append(table_key)

    return {
        "ok": True,
        "event_id": _event_id(event),
        "completed_tables": completed,
        "table_results": results,
    }


def deliver_with_outbox(
    new_event: dict | None,
    pending_path: Path,
    payload_root: Path,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout_seconds: int = 20,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict:
    """Deliver pending/current POMS publication events in dependency order.

    New events are snapshotted before delivery so a later retry sends the exact
    formal files that belonged to that 15-minute/hourly publication slot.
    """
    pending = _read_jsonl(pending_path)
    if new_event is not None:
        pending.append(_snapshot_event(new_event, payload_root))

    unique = []
    seen = set()
    for event in pending:
        event_id = _event_id(event)
        if not event_id or event_id in seen:
            continue
        event = dict(event)
        event["event_id"] = event_id
        unique.append(event)
        seen.add(event_id)

    if not unique:
        _write_events(pending_path, [])
        return {
            "ok": True,
            "delivery_state": "idle",
            "delivered_events": 0,
            "pending_events": 0,
        }

    resolved_url = _text(base_url or os.environ.get("POMS_URL"))
    resolved_key = _text(api_key or os.environ.get("POMS_API_KEY"))
    if not resolved_url or not resolved_key:
        _write_events(pending_path, unique)
        missing = []
        if not resolved_url:
            missing.append("POMS_URL")
        if not resolved_key:
            missing.append("POMS_API_KEY")
        return {
            "ok": False,
            "delivery_state": "pending_configuration",
            "missing": missing,
            "delivered_events": 0,
            "pending_events": len(unique),
        }

    delivered = 0
    last_result = None
    for index, event in enumerate(unique):
        result = deliver_publication_event(
            event,
            resolved_url,
            resolved_key,
            timeout_seconds=timeout_seconds,
            batch_size=batch_size,
        )
        last_result = result
        if not result.get("ok"):
            remaining = unique[index:]
            _write_events(pending_path, remaining)
            return {
                "ok": False,
                "delivery_state": "pending_retry",
                "delivered_events": delivered,
                "pending_events": len(remaining),
                "last_result": result,
            }
        delivered += 1
        _cleanup_snapshot(event)

    _write_events(pending_path, [])
    return {
        "ok": True,
        "delivery_state": "delivered",
        "delivered_events": delivered,
        "pending_events": 0,
        "last_result": last_result,
    }
