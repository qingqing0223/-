"""Atomic, offline frontend snapshots. Detail failures never gate basic records.

The raw feed preserves unknown values. POMS arrays are a separate transport view,
with every substituted value listed in metadata rather than treated as evidence.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit

from .common import CN_TZ
from .mp_display import ACCOUNT_ID_NOTE, COMMENT_NOTE, ZERO_NOTE, empty, normalize_tables
from .mp_export import FIELDS, build_tables
from .mp_poms import POMS_FIELDS, poms_rows, validate_schema


def _get(state, key, default=None):
    return state.get(key, default) if isinstance(state, dict) else getattr(state, key, default)


def _time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(CN_TZ) if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def _atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _sources(record):
    sources = record.get("discovery_sources") or []
    if isinstance(sources, str):
        sources = [sources]
    return sorted(set(sources or (["sogou"] if record.get("history_batch") else [])))


def _counts(rows):
    return {
        "total_candidates": len(rows),
        "valid_articles": sum(r.get("review_status") == "是" for r in rows),
        "pending_review_articles": sum(r.get("review_status") == "待核验" for r in rows),
        "invalid_articles": sum(r.get("review_status") == "否" for r in rows),
        "canonical_urls": sum(bool(r.get("canonical_url")) for r in rows),
        "url_unresolved": sum(not r.get("canonical_url") for r in rows),
    }


def _transport(raw_tables):
    """Validate each row: an incompatible row cannot block unrelated records."""
    conflicts, arrays = [], [[] for _ in range(5)]
    try:
        normalized = normalize_tables(raw_tables)
    except (ValueError, TypeError) as exc:
        normalized = None
        conflicts.append({"table": "all", "field": "normalization", "reason": str(exc),
                          "action": "isolate_rows"})
    placeholders = []
    for index, rows in enumerate(raw_tables):
        for row_index, raw in enumerate(rows):
            try:
                if normalized is None:
                    isolated = [[] for _ in range(5)]
                    isolated[index] = [raw]
                    values = normalize_tables(isolated)[index][0]
                else:
                    values = normalized[index][row_index]
                obj = poms_rows(index, [values])[0]
                isolated = [[] for _ in range(5)]
                isolated[index] = [obj]
                validate_schema(isolated)
                arrays[index].append(obj)
                for column, value in enumerate(raw):
                    if empty(value):
                        placeholders.append({"table": f"table{index+1}", "record_id": str(raw[0]),
                                             "field": POMS_FIELDS[index][column], "source_value": value,
                                             "transport_value": obj[POMS_FIELDS[index][column]],
                                             "is_observation": False})
            except (ValueError, TypeError, KeyError) as exc:
                reason = str(exc)
                field = reason.split("field=", 1)[1].split()[0] if "field=" in reason else "normalization"
                conflicts.append({"table": f"table{index+1}", "record_id": str(raw[0]),
                                  "row": row_index + 1, "field": field, "reason": reason,
                                  "action": "exclude_from_poms_only"})
    # Never emit dependent rows whose corresponding basic row failed validation.
    content_ids = {r["published_content_id"] for r in arrays[0]}
    for index in (1, 2, 3):
        retained = []
        for row in arrays[index]:
            if row["corresponding_published_content_id"] in content_ids:
                retained.append(row)
            else:
                conflicts.append({"table": f"table{index+1}", "record_id": row["corresponding_published_content_id"],
                                  "field": "corresponding_published_content_id", "reason": "basic_row_not_submittable",
                                  "action": "exclude_from_poms_only"})
        arrays[index] = retained
    return arrays, conflicts, placeholders


def export_frontend(cfg: dict, state) -> dict:
    """Export a self-contained latest.json and five raw/POMS JSON arrays.

    This function performs no network requests, never uploads to POMS, and never
    writes into the historical input directory. Consumers requiring a consistent
    generation should read latest.json (all data is embedded in one atomic file).
    """
    original = _get(state, "records", [])
    records = deepcopy(list(original.values()) if isinstance(original, dict) else list(original))
    stamp = cfg.get("wechat_mp_exported_at") or datetime.now(CN_TZ).isoformat(timespec="seconds")
    now = _time(stamp)
    if now is None:
        raise ValueError("wechat_mp_exported_at must include a timezone")
    period_start = _time(cfg.get("current_period_start") or cfg.get("monitoring_start_time"))
    period_end = _time(cfg.get("current_period_end") or cfg.get("monitoring_end_time"))
    directory = Path(cfg.get("wechat_mp_frontend_root", "data_submissions/wechat_mp/2026-09-23_wechatmp03/frontend"))
    if directory.suffix == ".json":
        raise ValueError("wechat_mp_frontend_root must be a directory")
    catalog_path = Path(cfg.get("wechat_mp_key_accounts", "config/key_accounts.wechat_mp.json"))
    catalog = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.is_file() else {}
    eligible, quarantine = [], []
    for record in records + deepcopy(_get(state, 'discoveries', [])):
        reasons = []
        for key in ("content_id", "title", "author"):
            if empty(record.get(key)):
                reasons.append(f"missing_{key}")
        if _time(record.get("publish_time")) is None:
            reasons.append("missing_or_unreliable_publish_time")
        try:
            link = urlsplit(record.get("canonical_url") or record.get("url") or "")
            if link.scheme not in ("http", "https") or link.hostname not in ("weixin.sogou.com", "mp.weixin.qq.com"):
                reasons.append("missing_public_article_or_result_url")
        except ValueError:
            reasons.append("invalid_public_url")
        if not record.get("candidate_eligible"):
            reasons.append("candidate_not_eligible")
        if reasons:
            quarantine.append({"record": record, "reasons": reasons})
        else:
            eligible.append(record)
    raw_tables = build_tables(eligible, catalog, stamp)
    arrays, conflicts, placeholders = _transport(raw_tables)
    for entry in quarantine:
        if "missing_or_unreliable_publish_time" in entry["reasons"]:
            conflicts.append({"table": "table1", "record_id": entry["record"].get("content_id"),
                              "field": "published_at", "reason": "required_timezone_datetime_unavailable",
                              "action": "retain_quarantine_evidence; do_not_fabricate_timestamp"})
    history = [r for r in eligible if r.get("history_batch")]
    current = [r for r in eligible if period_start and _time(r.get("publish_time")) >= period_start
               and (not period_end or _time(r.get("publish_time")) <= period_end)]
    today = [r for r in eligible if _time(r.get("publish_time")).date() == now.date()]
    newly_discovered = [r for r in eligible if not r.get("history_batch") and
                        _time(r.get("first_discovered_at")) and
                        _time(r["first_discovered_at"]).date() == now.date()]
    enriched_today = [r for r in eligible if _time(r.get("detail_completed_at")) and
                      _time(r["detail_completed_at"]).date() == now.date()]
    sources = sorted({source for r in eligible for source in _sources(r)})
    source_status = deepcopy(_get(state, "source_status", {}))
    configured_sources = cfg.get("wechat_mp_discovery_sources", ["sogou", "bing"])
    for name in ("sogou", "google", "bing"):
        if name not in configured_sources:
            source_status.setdefault(name, {"status": "DISABLED", "reason": "disabled_by_configuration"})
        else:
            source_status.setdefault(name, {"status": "NOT_STARTED", "reason": "no_confirmed_live_search"})
    all_observations = [_time(r.get('collected_at')) for r in records + deepcopy(_get(state, 'discoveries', []))]
    observed = max((value for value in all_observations if value), default=None)
    evidence = [_time(s.get('last_evidence_at')) for s in source_status.values()]
    live_evidence = max((value for value in evidence if value), default=None)
    collection = {
        'status': 'LIVE_EVIDENCE_OBSERVED' if live_evidence else 'NO_LIVE_EVIDENCE',
        'last_live_evidence_at': live_evidence.isoformat() if live_evidence else None,
        'enabled_sources': list(configured_sources),
        'source_status': {name: s.get('status', 'UNKNOWN') for name, s in source_status.items()},
        'note': 'Snapshot refresh is not a successful live crawl. Historical records remain historical.',
    }
    field_availability = {}
    tables = {}
    for index, (rows, fields) in enumerate(zip(raw_tables, FIELDS), 1):
        name = f"table{index}"
        tables[name] = [dict(zip(fields, row)) for row in rows]
        field_availability[name] = [
            {"record_id": str(row[0]), "fields": {field: {"available": not empty(value),
             "status": "observed_or_derived" if not empty(value) else "not_obtained"}
             for field, value in zip(fields, row)}} for row in rows]
    metrics = {}
    valid = [r for r in eligible if r.get("review_status") == "是"]
    for field in ("views", "likes", "comments", "reposts", "shares", "favorites"):
        values = [r.get(field) for r in valid]
        known = [v for v in values if type(v) is int and v >= 0]
        metrics[field] = {"known_sum": sum(known) if known else None, "known_records": len(known),
                          "unknown_records": len(values)-len(known),
                          "complete_sum": sum(known) if values and len(known) == len(values) else None}
    metadata = {
        "platform": "wechat_mp", "exported_at": stamp, "generation_id": uuid4().hex,
        "current_period_start": period_start.isoformat() if period_start else None,
        "current_period_end": period_end.isoformat() if period_end else None,
        "cumulative": _counts(eligible), "history": _counts(history),
        "published_today": _counts(today), "current_period": _counts(current),
        "new_discoveries_today": _counts(newly_discovered), "details_completed_today": len(enriched_today),
        "history_batches": {name: _counts([r for r in history if r["history_batch"] == name])
                            for name in sorted({str(r["history_batch"]) for r in history})},
        "history_input_paths": deepcopy(_get(state, 'history_import_paths', {})),
        "source_counts": {source: _counts([r for r in eligible if source in _sources(r)]) for source in sources},
        "source_status": source_status, "queue_jobs": deepcopy(_get(state, "queue_jobs", [])),
        "last_observation_at": observed.isoformat() if observed else None,
        "collection": collection,
        "quarantine_count": len(quarantine), "schema_conflict_count": len(conflicts),
        "table_counts": [len(t) for t in raw_tables], "poms_table_counts": [len(t) for t in arrays],
        "field_availability": field_availability, "poms_placeholders": placeholders,
        "reliable_interactions": metrics, "zero_placeholder_note": ZERO_NOTE,
        "account_id_note": ACCOUNT_ID_NOTE, "comment_note": COMMENT_NOTE,
        "scope_note": "历史、今日发布时间、本期发布时间、新发现、详情补采分别统计。表3/5仅汇总确认有效文章；未知互动不计为真实0。",
        "url_note": "canonical_url未取得不阻塞基础供数；保留真实搜狗链接。链接类型/补全状态见records，不添加POMS schema外字段。",
        "poms_note": "POMS待核验以false表示尚未确认为有效，原因保留；永久URL、官方帐号ID和完整互动不是本地基础供数前置条件。",
    }
    snapshot = {"schema_version": 1, "metadata": metadata, "tables": tables,
                "records": records, "quarantine": quarantine, "schema_conflicts": conflicts,
                "poms_tables": {f"table{i+1}": rows for i, rows in enumerate(arrays)}}
    for index in range(1, 6):
        _atomic(directory / f"table{index}.json", tables[f"table{index}"])
        _atomic(directory / f"table{index}_batch.json", arrays[index-1])
    _atomic(directory / "schema_conflicts.json", conflicts)
    _atomic(directory / "metadata.json", metadata)
    _atomic(directory / "latest.json", snapshot)
    return {"directory": str(directory), "latest": str(directory / "latest.json"),
            "table_counts": metadata["table_counts"], "poms_table_counts": metadata["poms_table_counts"],
            "schema_conflicts": conflicts, "metadata": metadata}
