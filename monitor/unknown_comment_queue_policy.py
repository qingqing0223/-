from __future__ import annotations

SUPPORTED = {"xhs", "bili", "wb", "toutiao", "zhihu"}


def install_unknown_comment_count_fallback(platform: str) -> None:
    """Queue newly discovered content even when search rows omit comment counts.

    This is a queue-only signal. It never writes a fabricated comment count back
    to persisted content. The shared realtime detail policy still enforces bounded
    candidate counts, time budgets and per-item comment caps.
    """
    if platform not in SUPPORTED:
        return

    import monitor.crawler_runner as crawler_runner

    marker = f"_promotion_week_unknown_comment_fallback_{platform}"
    if getattr(crawler_runner, marker, False):
        return

    original_update = crawler_runner._update_queue_from_content

    def update_with_unknown_count_fallback(actual_platform: str, content_files, queue: dict) -> None:
        original_update(actual_platform, content_files, queue)
        if actual_platform != platform:
            return

        for item in (queue.get("items") or {}).values():
            if not isinstance(item, dict):
                continue
            visible = int(item.get("visible_comment_count") or 0)
            if visible > 0:
                item["queue_signal"] = "visible_comment_count"
                item["comment_count_unknown"] = False
                continue

            # Queue priority only. Do not persist this synthetic value into raw data.
            item["visible_comment_count"] = 1
            item["queue_signal"] = f"{platform}_unknown_comment_count"
            item["comment_count_unknown"] = True

    crawler_runner._update_queue_from_content = update_with_unknown_count_fallback
    setattr(crawler_runner, marker, True)
