from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pipeline.classifier import classify_records
from pipeline.io_utils import append_jsonl, read_jsonl, read_json, write_json
from pipeline.normalizer import normalize_record
from .ingest import _prepare_region_aliases, _before_monitoring_start


CLASSIFICATION_FIELDS = (
    "status", "type", "source_type", "source_type_method", "video_content_type",
    "video_attitude_status", "video_attitude_type", "video_attitude_scope",
    "post_attitude_status", "post_attitude_type",
    "audience_attitude_status", "audience_attitude_type",
)


def _load_latest_classified(path: Path) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    if not path.exists():
        return latest
    for row in read_jsonl(path):
        key = str(row.get("dedupe_key") or "")
        if key:
            latest[key] = row
    return latest


def ingest_key_account_snapshot(
    platform: str,
    jsonl_files: list[Path],
    state_path: Path,
    output_jsonl: Path,
    concurrency: int = 4,
    monitoring_start_time: str = "",
) -> dict:
    """Classify new creator posts and refresh engagement for already-seen posts.

    Existing items keep their prior v2/source labels; only public metadata and
    interaction counters are refreshed.  The returned push_rows can therefore be
    sent to Suqi's upsert-capable backend without paying for repeated model calls.
    """
    seen_data = read_json(state_path, {"seen": []})
    seen = set(map(str, seen_data.get("seen", [])))
    previous = _load_latest_classified(output_jsonl)

    current: dict[str, dict] = {}
    for path in jsonl_files:
        for raw in read_jsonl(path):
            rec = normalize_record(_prepare_region_aliases(raw), source_file=path.name, platform_hint=platform)
            if not rec:
                continue
            if _before_monitoring_start(rec, monitoring_start_time):
                continue
            current[rec["dedupe_key"]] = rec

    fresh = [rec for key, rec in current.items() if key not in seen]
    fresh_classified = classify_records(fresh, concurrency=concurrency)
    fresh_by_key = {row["dedupe_key"]: row for row in fresh_classified}

    refreshed = []
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    for key, rec in current.items():
        if key in fresh_by_key:
            continue
        old = previous.get(key)
        if not old:
            # State and output can get out of sync after manual file operations.
            # Reclassify this record instead of emitting an unlabelled refresh.
            row = classify_records([rec], concurrency=1)[0]
            fresh_classified.append(row)
            fresh_by_key[key] = row
            continue

        row = dict(old)
        old_first_seen = row.get("first_seen_time")
        row.update(rec)
        if old_first_seen:
            row["first_seen_time"] = old_first_seen
        # Defensive preservation if a future normalizer introduces overlapping keys.
        for field in CLASSIFICATION_FIELDS:
            if field in old:
                row[field] = old[field]
        row["engagement_refresh_time"] = now
        row["key_account_refresh"] = True
        refreshed.append(row)

    push_rows = fresh_classified + refreshed
    # Append both new classifications and refreshed snapshots so privacy-safe
    # aggregate summaries can use the most recent engagement values per content id.
    append_jsonl(output_jsonl, push_rows)

    for row in fresh_classified:
        seen.add(row["dedupe_key"])
    write_json(state_path, {"seen": sorted(seen)})

    return {
        "platform": platform,
        "monitoring_start_time": monitoring_start_time,
        "snapshot_records": len(current),
        "new_records": len(fresh_classified),
        "engagement_refresh_records": len(refreshed),
        "push_rows": push_rows,
        "total_seen": len(seen),
    }
