from __future__ import annotations

from datetime import datetime
from pathlib import Path

import monitor.crawler_runner as crawler_runner
from monitor.ingest import _parse_iso_datetime
from pipeline.normalizer import normalize_record


MARKER = "_promotion_week_wb_monitoring_scope_queue_policy"


def _content_scope_map(
    content_files: list[Path],
    monitoring_start_time: str,
) -> dict[str, str]:
    start = _parse_iso_datetime(monitoring_start_time)
    if start is None:
        return {}

    scope: dict[str, str] = {}

    for row in crawler_runner._iter_jsonl(content_files):
        identifier = crawler_runner._detail_identifier("wb", row)
        if not identifier:
            continue

        rec = normalize_record(
            row,
            source_file="",
            platform_hint="wb",
        )
        if not rec:
            continue

        published = _parse_iso_datetime(
            rec.get("publish_time"),
            default_tz=start.tzinfo,
        )
        if published is None:
            continue

        if published < start:
            if scope.get(identifier) != "in_scope":
                scope[identifier] = "before_start"
        else:
            scope[identifier] = "in_scope"

    return scope


def prune_queue_for_monitoring_scope(
    queue: dict,
    content_files: list[Path],
    monitoring_start_time: str,
) -> int:
    scope = _content_scope_map(content_files, monitoring_start_time)
    items = queue.get("items") or {}

    removed = 0
    for identifier, status in scope.items():
        if status == "before_start" and identifier in items:
            del items[identifier]
            removed += 1

    return removed


def _historical_content_files(data_root: str) -> list[Path]:
    raw_root = Path(data_root) / "raw_runs"
    if not raw_root.exists():
        return []

    return sorted(
        p for p in raw_root.rglob("*.jsonl")
        if "content" in p.name.lower()
        and "comment" not in p.name.lower()
    )


def install_weibo_monitoring_scope_queue_policy(
    data_root: str,
    monitoring_start_time: str,
) -> None:
    if getattr(crawler_runner, MARKER, False):
        return

    monitoring_start_time = str(monitoring_start_time or "").strip()
    if not monitoring_start_time:
        return

    qpath = crawler_runner._queue_path({"data_root": data_root}, "wb")
    queue = crawler_runner._load_queue(qpath)

    # One-time cleanup of previously accumulated queue entries.
    if (
        qpath.exists()
        and queue.get("monitoring_scope_pruned_for") != monitoring_start_time
    ):
        removed = prune_queue_for_monitoring_scope(
            queue,
            _historical_content_files(data_root),
            monitoring_start_time,
        )
        queue["monitoring_scope_pruned_for"] = monitoring_start_time
        queue["monitoring_scope_pruned_count"] = removed
        queue["updated_at"] = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        crawler_runner._save_queue(qpath, queue)

    original_update = crawler_runner._update_queue_from_content

    def update_weibo_queue(actual_platform, content_files, queue):
        original_update(actual_platform, content_files, queue)

        if actual_platform != "wb":
            return

        removed = prune_queue_for_monitoring_scope(
            queue,
            content_files,
            monitoring_start_time,
        )
        if removed:
            queue["monitoring_scope_last_drop_count"] = removed

    crawler_runner._update_queue_from_content = update_weibo_queue
    setattr(crawler_runner, MARKER, True)