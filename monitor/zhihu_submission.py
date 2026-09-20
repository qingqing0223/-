from __future__ import annotations

"""Export Zhihu collection-only data into the five agreed submission tables.

This module deliberately does not assign attitude or issue labels.  It accepts
only records whose visible title/body contains a configured campaign phrase,
keeps raw IDs as strings, and writes unavailable public values as empty strings.
"""

from datetime import datetime, timezone
import json
from pathlib import Path

from pipeline.normalizer import normalize_record


TABLES = {
    "table1_content.jsonl": "content_id",
    "table2_comments.jsonl": "comment_id",
    "table3_content_engagement.jsonl": "snapshot_key",
    "table4_comment_engagement.jsonl": "snapshot_key",
    "table5_accounts.jsonl": "author_id",
}


def _read_rows(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    temp.replace(path)


def _parse_time(value: str):
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _in_scope(record: dict, keywords: list[str], monitoring_start_time: str, require_topic: bool = True) -> tuple[bool, str]:
    published = _parse_time(record.get("publish_time", ""))
    start = _parse_time(monitoring_start_time)
    if published and start:
        if published.tzinfo is None and start.tzinfo is not None:
            published = published.replace(tzinfo=start.tzinfo)
        if published < start:
            return False, "发布时间早于正式监测起点"
    visible_text = "\n".join((record.get("content", ""), record.get("context", "")))
    if require_topic and not any(term and term in visible_text for term in keywords):
        return False, "可见标题或正文未出现正式主题关键词"
    return True, ""


def _merge(existing: dict, incoming: dict, key: str) -> dict:
    out = dict(existing)
    for name, value in incoming.items():
        if value not in (None, ""):
            out[name] = value
    matches = set(existing.get("matched_keywords") or [])
    matches.update(incoming.get("matched_keywords") or [])
    out["matched_keywords"] = sorted(matches)
    out[key] = str(out.get(key) or incoming.get(key) or "")
    return out


def export_zhihu_submission(
    raw_files: list[Path],
    cfg: dict,
    repo_root: Path,
    node_id: str,
) -> dict:
    """Merge one raw cycle into data_submissions/zhihu/<node>/<date>/ tables."""
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    date = datetime.now().astimezone().date().isoformat()
    output = repo_root / "data_submissions" / "zhihu" / node_id / date
    keywords = [str(x).strip() for x in cfg.get("keywords", []) if str(x).strip()]
    kept, excluded, content_count, comment_count = 0, 0, 0, 0
    contents: dict[str, dict] = {}
    comments: dict[str, dict] = {}
    content_snaps: list[dict] = []
    comment_snaps: list[dict] = []
    accounts: dict[str, dict] = {}
    raw_rows = [(path, raw) for path in raw_files for raw in _read_rows(path)]
    valid_content_ids: set[str] = set()

    # Validate the parent posts first. Comments are in scope because their
    # parent is in scope; a reply need not repeat the campaign phrase itself.
    for raw_path, raw in raw_rows:
            probe = normalize_record(raw, source_file=raw_path.name, platform_hint="zhihu")
            if not probe or probe.get("record_type") == "comment":
                continue
            valid, _ = _in_scope(probe, keywords, str(cfg.get("monitoring_start_time") or ""))
            if valid and probe.get("content_id"):
                valid_content_ids.add(str(probe["content_id"]))

    for raw_path, raw in raw_rows:
            record = normalize_record(raw, source_file=raw_path.name, platform_hint="zhihu")
            if not record or record.get("platform") != "zhihu":
                continue
            is_comment = record.get("record_type") == "comment"
            valid, reason = _in_scope(
                record, keywords, str(cfg.get("monitoring_start_time") or ""), require_topic=not is_comment
            )
            if is_comment and str(record.get("content_id") or "") not in valid_content_ids:
                valid, reason = False, "父内容不属于本次主题监测范围"
            if not valid:
                excluded += 1
                continue
            keyword = str(record.get("source_keyword") or "").strip()
            matches = [keyword] if keyword in keywords else [term for term in keywords if term in (record.get("content", "") + record.get("context", ""))]
            record["matched_keywords"] = matches
            record["collection_time"] = now
            kept += 1
            if is_comment:
                comment_count += 1
                cid = str(record.get("comment_id") or "")
                if not cid:
                    continue
                comments[cid] = _merge(comments.get(cid, {}), {
                    "content_id": str(record.get("content_id") or ""), "comment_id": cid,
                    "platform": "zhihu", "comment_user_id": str(record.get("author_id") or ""),
                    "comment_user_ip_location": str(record.get("ip_location") or ""),
                    "comment_text": record.get("content", ""), "comment_publish_time": record.get("publish_time", ""),
                    "parent_comment_id": str(record.get("parent_comment_id") or ""),
                    "root_comment_id": str(record.get("root_comment_id") or ""),
                    "comment_level": record.get("comment_level", 1), "is_valid_comment": True,
                    "invalid_reason": "", "matched_keywords": matches, "collection_time": now,
                }, "comment_id")
                comment_snaps.append({
                    "content_id": str(record.get("content_id") or ""), "comment_id": cid, "platform": "zhihu",
                    "snapshot_time": now, "comment_reply_count": raw.get("sub_comment_count", ""),
                    "comment_like_count": raw.get("like_count", ""),
                })
                continue
            content_count += 1
            cid = str(record.get("content_id") or "")
            if not cid:
                continue
            contents[cid] = _merge(contents.get(cid, {}), {
                "content_id": cid, "platform": "zhihu", "author_id": str(record.get("author_id") or ""),
                "author_name": record.get("author", ""), "author_ip_location": str(record.get("ip_location") or ""),
                "account_type": "", "content_type": raw.get("content_type", record.get("record_type", "")),
                "title": raw.get("title", ""), "content_text": record.get("content", ""),
                "publish_time": record.get("publish_time", ""), "collection_time": now,
                "original_url": record.get("url", ""), "matched_keywords": matches,
                "original_or_repost": "", "is_valid_monitoring_data": True, "invalid_reason": "",
            }, "content_id")
            content_snaps.append({
                "content_id": cid, "platform": "zhihu", "snapshot_time": now,
                "view_count": raw.get("view_count", ""), "like_count": raw.get("voteup_count", ""),
                "comment_count": raw.get("comment_count", ""), "repost_count": "", "share_count": "",
                "favorite_count": raw.get("favorite_count", ""),
            })
            author_id = str(record.get("author_id") or "")
            if author_id:
                accounts[author_id] = {
                    "author_id": author_id, "platform": "zhihu", "author_name": record.get("author", ""),
                    "profile_url": record.get("author_profile_url", ""), "account_type": "", "fan_count": "",
                    "following_count": "", "region": str(record.get("ip_location") or ""), "organization": "",
                    "is_key_account": False, "related_post_count": "", "view_count": "", "like_count": "",
                    "comment_count": "", "repost_count": "", "favorite_count": "", "total_engagement": "",
                    "collection_time": now,
                }

    for filename, incoming, key in (
        ("table1_content.jsonl", contents.values(), "content_id"),
        ("table2_comments.jsonl", comments.values(), "comment_id"),
        ("table5_accounts.jsonl", accounts.values(), "author_id"),
    ):
        existing = {str(row.get(key) or ""): row for row in _read_rows(output / filename) if row.get(key)}
        for row in incoming:
            existing[str(row[key])] = _merge(existing.get(str(row[key]), {}), row, key)
        _write_rows(output / filename, [existing[key] for key in sorted(existing)])
    for filename, rows in (("table3_content_engagement.jsonl", content_snaps), ("table4_comment_engagement.jsonl", comment_snaps)):
        for row in rows:
            row["snapshot_key"] = f"{row.get('content_id','')}:{row.get('comment_id','')}:{row['snapshot_time']}"
        _write_rows(output / filename, _read_rows(output / filename) + rows)
    manifest = {"platform": "zhihu", "node_id": node_id, "generated_at": now, "keywords": keywords,
                "accepted_rows": kept, "excluded_rows": excluded, "content_rows_this_cycle": content_count,
                "comment_rows_this_cycle": comment_count, "classification": "not_run_collection_group_scope_only"}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**manifest, "output_dir": str(output)}
