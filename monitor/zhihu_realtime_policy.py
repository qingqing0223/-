from __future__ import annotations

"""Zhihu-only realtime queue/state policy.

The shared crawler queues every search hit before the submission exporter applies
the formal monitoring scope. For Zhihu this caused old/out-of-scope search hits to
consume the bounded detail-comment budget. This module installs a process-local
wrapper that:

1. admits only formally in-scope Zhihu content to the deep-comment queue;
2. purges legacy unvalidated Zhihu queue entries;
3. treats a bounded Zhihu detail timeout after successful discovery as
   PARTIAL_SUCCESS rather than a platform-wide NETWORK_ERROR.

No shared crawler source is modified and other platforms are unchanged.
"""

from datetime import datetime, timezone
from pathlib import Path

from pipeline.normalizer import normalize_record
from .zhihu_submission import _in_scope, _matched_keywords


SCOPE_POLICY_VERSION = "zhihu_strict_scope_v1"


def _has_public_comment_count(row: dict, keys: tuple[str, ...]) -> bool:
    return any(key in row and row.get(key) not in (None, "") for key in keys)


def install_zhihu_scope_aware_realtime_policy(cfg: dict) -> None:
    import monitor.crawler_runner as crawler_runner

    marker = "_promotion_week_zhihu_scope_aware_realtime_policy"
    if getattr(crawler_runner, marker, False):
        return

    original_update = crawler_runner._update_queue_from_content
    original_classify = crawler_runner._classify_state

    keywords = [
        str(x).strip()
        for x in cfg.get("keywords", [])
        if str(x).strip()
    ]
    monitoring_start = str(cfg.get("monitoring_start_time") or "")
    require_publish_time = bool(cfg.get("zhihu_require_publish_time", True))

    def update_scope_filtered_queue(
        actual_platform: str,
        content_files: list[Path],
        queue: dict,
    ) -> None:
        if actual_platform != "zhihu":
            original_update(actual_platform, content_files, queue)
            return

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        items = queue.setdefault("items", {})

        # Purge queue rows created before strict-scope validation existed.
        # Keeping them would let stale pre-2026-09-16 results consume detail time.
        for identifier in list(items):
            item = items.get(identifier)
            if not isinstance(item, dict) or item.get("scope_policy_version") != SCOPE_POLICY_VERSION:
                items.pop(identifier, None)

        for raw in crawler_runner._iter_jsonl(content_files):
            record = normalize_record(
                raw,
                source_file="zhihu_realtime_search",
                platform_hint="zhihu",
            )
            if (
                not record
                or record.get("platform") != "zhihu"
                or record.get("record_type") == "comment"
            ):
                continue

            identifier = crawler_runner._detail_identifier("zhihu", raw)
            if not identifier:
                continue

            valid, reason = _in_scope(
                record,
                keywords,
                monitoring_start,
                require_topic=True,
                require_publish_time=require_publish_time,
            )
            if not valid:
                items.pop(identifier, None)
                continue

            visible = crawler_runner._visible_comment_count(raw)
            has_public_count = _has_public_comment_count(
                raw,
                crawler_runner._COMMENT_COUNT_KEYS,
            )

            item = items.setdefault(
                identifier,
                {
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "last_deep_crawled_at": "",
                    "visible_comment_count": 0,
                    "retry_count": 0,
                },
            )
            item["last_seen_at"] = now
            item["scope_policy_version"] = SCOPE_POLICY_VERSION
            item["scope_validated"] = True
            item["scope_reason"] = reason
            item["publish_time"] = str(record.get("publish_time") or "")
            item["matched_keywords"] = _matched_keywords(record, keywords)

            if has_public_count:
                item["visible_comment_count"] = int(visible)
                item["comment_count_unknown"] = False
                item["queue_signal"] = "visible_comment_count"
            else:
                # Queue-only sentinel. It is never persisted as a real metric.
                item["visible_comment_count"] = 1
                item["comment_count_unknown"] = True
                item["queue_signal"] = "zhihu_unknown_comment_count"

        queue["scope_policy_version"] = SCOPE_POLICY_VERSION

    def classify_zhihu_partial_success(
        return_code: int | None,
        stdout_log: Path,
        stderr_log: Path,
        runner_error: str = "",
        *,
        content_row_count: int = 0,
        comment_row_count: int = 0,
        comments_enabled: bool = False,
    ) -> str:
        state = original_classify(
            return_code,
            stdout_log,
            stderr_log,
            runner_error=runner_error,
            content_row_count=content_row_count,
            comment_row_count=comment_row_count,
            comments_enabled=comments_enabled,
        )
        if state != "NETWORK_ERROR" or content_row_count <= 0:
            return state

        text = crawler_runner._tail_text(stdout_log, stderr_log)
        if "zhihu_realtime_detail_candidate_timeout" in text:
            return "PARTIAL_SUCCESS"
        return state

    crawler_runner._update_queue_from_content = update_scope_filtered_queue
    crawler_runner._classify_state = classify_zhihu_partial_success
    setattr(crawler_runner, marker, True)
