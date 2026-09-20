from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pipeline.normalizer import normalize_record


def _read_rows(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows

    with path.open("r", encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)

    return rows


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")

    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    tmp.replace(path)


def _parse_time(value):
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _normalize_topic_text(value: str) -> str:
    text = str(value or "")

    replacements = {
        "\uff0c": ",",
        "\u3002": ".",
        "\uff1a": ":",
        "\uff1b": ";",
        "\uff01": "!",
        "\uff1f": "?",
        "\u2014": "-",
        "\u2013": "-",
        "\uff0d": "-",
        "\u3000": " ",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    for ch in (
        " ", "\t", "\r", "\n",
        ",", ".", ":", ";", "!", "?",
        "-", "_",
        "\u00b7",
        "\u201c", "\u201d",
        '"', "'",
        "\uff08", "\uff09",
        "(", ")",
        "#",
    ):
        text = text.replace(ch, "")

    return text


def _matched_keywords(record: dict, keywords: list[str]) -> list[str]:
    visible = "\n".join((
        str(record.get("content") or ""),
        str(record.get("context") or ""),
    ))

    normalized = _normalize_topic_text(visible)

    return list(dict.fromkeys(
        keyword
        for keyword in keywords
        if _normalize_topic_text(keyword) in normalized
    ))



def _load_scope_overrides(repo_root: Path) -> tuple[set[str], dict[str, str]]:
    path = repo_root / "config" / "weibo_scope_overrides.json"

    if not path.exists():
        return set(), {}

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return set(), {}

    force_valid = {
        str(x).strip()
        for x in data.get("force_valid_content_ids", [])
        if str(x).strip()
    }

    excluded = {
        str(k).strip(): str(v or "").strip()
        for k, v in (data.get("exclude_content_ids") or {}).items()
        if str(k).strip()
    }

    return force_valid, excluded


def _load_account_types(
    repo_root: Path,
    cfg: dict,
) -> dict[str, str]:
    catalog_name = str(
        cfg.get("key_account_catalog")
        or "config/key_accounts.v3.catalog.json"
    ).strip()

    path = Path(catalog_name)
    if not path.is_absolute():
        path = repo_root / path

    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}

    result = {}

    for category in data.get("categories") or []:
        if not isinstance(category, dict):
            continue

        account_type = str(
            category.get("account_type") or ""
        ).strip()

        for raw_name in category.get("accounts") or []:
            canonical = str(raw_name or "").strip()
            if not canonical:
                continue

            result[canonical] = account_type

            for alias in canonical.replace("\uff0f", "/").split("/"):
                alias = alias.strip()
                if alias:
                    result.setdefault(alias, account_type)

    return result


def _monitoring_validity(
    record: dict,
    matches: list[str],
    monitoring_start_time: str,
) -> tuple[bool, str]:
    published = _parse_time(record.get("publish_time"))
    start = _parse_time(monitoring_start_time)

    if published is None:
        return (
            False,
            "\u53d1\u5e03\u65f6\u95f4\u7f3a\u5931\u6216\u65e0\u6cd5\u89e3\u6790",
        )

    if start is not None:
        if published.tzinfo is None and start.tzinfo is not None:
            published = published.replace(tzinfo=start.tzinfo)

        if published < start:
            return (
                False,
                "\u53d1\u5e03\u65f6\u95f4\u65e9\u4e8e\u6b63\u5f0f\u76d1\u6d4b\u8d77\u70b9",
            )

    if not matches:
        return (
            False,
            "\u6807\u9898/\u6b63\u6587\u672a\u547d\u4e2d\u5b8c\u6574\u6b63\u5f0f\u4e3b\u9898\u5173\u952e\u8bcd\uff0c\u5f85\u4e3b\u9898\u76f8\u5173\u6027\u590d\u6838",
        )

    return True, ""


def _merge_table1(existing: dict, incoming: dict) -> dict:
    if not existing:
        return dict(incoming)

    out = dict(existing)

    matches = set(existing.get("matched_keywords") or [])
    matches.update(incoming.get("matched_keywords") or [])
    out["matched_keywords"] = sorted(matches)

    for key, value in incoming.items():
        if key == "matched_keywords":
            continue

        if key in {
            "collection_time",
            "is_valid_monitoring_data",
            "invalid_reason",
        }:
            out[key] = value
            continue

        if key not in out or value not in (None, "", []):
            out[key] = value

    return out


def export_weibo_table1(
    raw_files: list[Path],
    output_path: Path,
    cfg: dict,
    repo_root: Path,
) -> dict:
    """Export WB-only Tech Design V3 Table 1 rows."""

    now_text = datetime.now().astimezone().isoformat(timespec="seconds")

    keywords = [
        str(x).strip()
        for x in cfg.get("keywords", [])
        if str(x).strip()
    ]

    monitoring_start = str(
        cfg.get("monitoring_start_time")
        or "2026-09-16T00:00:00+08:00"
    )

    account_types = _load_account_types(repo_root, cfg)
    force_valid_ids, excluded_ids = _load_scope_overrides(repo_root)

    existing = {
        str(row.get("content_id") or ""): row
        for row in _read_rows(output_path)
        if row.get("content_id")
    }

    processed = 0
    valid_count = 0
    invalid_count = 0
    excluded_count = 0

    for raw_path in raw_files:
        for raw in _read_rows(raw_path):
            record = normalize_record(
                raw,
                source_file=raw_path.name,
                platform_hint="wb",
            )

            if not record:
                continue
            if record.get("platform") != "wb":
                continue
            if record.get("record_type") == "comment":
                continue

            content_id = str(
                record.get("content_id")
                or record.get("sample_id")
                or ""
            ).strip()

            if not content_id:
                continue

            # Explicit WB-only human review exclusion.
            if content_id in excluded_ids:
                existing.pop(content_id, None)
                excluded_count += 1
                continue

            author_name = str(record.get("author") or "").strip()

            matches = _matched_keywords(record, keywords)

            valid, invalid_reason = _monitoring_validity(
                record,
                matches,
                monitoring_start,
            )

            # Human review may override only topic-keyword strictness.
            # It must never bypass missing/old publish-time checks.
            topic_miss_reason = (
                "\u6807\u9898/\u6b63\u6587\u672a\u547d\u4e2d"
                "\u5b8c\u6574\u6b63\u5f0f\u4e3b\u9898\u5173\u952e\u8bcd"
            )

            if (
                not valid
                and content_id in force_valid_ids
                and str(invalid_reason).startswith(topic_miss_reason)
            ):
                valid = True
                invalid_reason = ""

            if valid:
                valid_count += 1
            else:
                invalid_count += 1

            incoming = {
                "content_id": content_id,
                "platform": "\u5fae\u535a",
                "author_id": str(record.get("author_id") or ""),
                "author_name": author_name,
                "author_ip_location": str(
                    record.get("ip_location") or ""
                ),
                "account_type": account_types.get(author_name, ""),
                "content_type": str(
                    record.get("record_type") or ""
                ),
                "title": str(record.get("context") or ""),
                "content_text": str(record.get("content") or ""),
                "publish_time": str(
                    record.get("publish_time") or ""
                ),
                "collection_time": now_text,
                "original_url": str(record.get("url") or ""),
                "matched_keywords": matches,
                "original_or_repost": str(
                    record.get("original_or_repost") or ""
                ),
                "is_valid_monitoring_data": valid,
                "invalid_reason": invalid_reason,
            }

            existing[content_id] = _merge_table1(
                existing.get(content_id, {}),
                incoming,
            )

            processed += 1

    rows = [existing[k] for k in sorted(existing)]
    _write_rows(output_path, rows)

    return {
        "processed": processed,
        "table1_rows": len(rows),
        "valid_rows_this_export": valid_count,
        "invalid_rows_this_export": invalid_count,
        "excluded_by_override": excluded_count,
        "output": str(output_path),
    }
