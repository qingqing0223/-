from __future__ import annotations

SUPPORTED = {"xhs", "bili", "wb", "toutiao", "zhihu"}


def install_unknown_comment_count_fallback(platform: str) -> None:
    """Queue only genuinely unknown public comment counts.

    For Bilibili an explicit public count of zero is meaningful and must not be
    converted into the synthetic probe value used for rows where the count field
    is absent. Other platforms retain the existing generic fallback behavior.
    """
    if platform not in SUPPORTED:
        return

    import monitor.crawler_runner as crawler_runner

    marker = f"_promotion_week_unknown_comment_fallback_{platform}"
    if getattr(crawler_runner, marker, False):
        return

    original_update = crawler_runner._update_queue_from_content

    if platform != "bili":
        def update_generic(actual_platform: str, content_files, queue: dict) -> None:
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
                item["visible_comment_count"] = 1
                item["queue_signal"] = f"{platform}_unknown_comment_count"
                item["comment_count_unknown"] = True

        crawler_runner._update_queue_from_content = update_generic
        setattr(crawler_runner, marker, True)
        return

    def has_explicit_comment_count(row: dict) -> bool:
        for key in crawler_runner._COMMENT_COUNT_KEYS:
            if key not in row:
                continue
            value = row.get(key)
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return True
        return False

    def update_bili(actual_platform: str, content_files, queue: dict) -> None:
        explicit_ids: set[str] = set()
        explicit_zero_ids: set[str] = set()
        unknown_ids: set[str] = set()

        if actual_platform == "bili":
            for row in crawler_runner._iter_jsonl(content_files):
                identifier = crawler_runner._detail_identifier("bili", row)
                if not identifier:
                    continue
                if has_explicit_comment_count(row):
                    explicit_ids.add(identifier)
                    if crawler_runner._visible_comment_count(row) <= 0:
                        explicit_zero_ids.add(identifier)
                else:
                    unknown_ids.add(identifier)

            # If the same video appears under multiple keywords, a real observed
            # count always wins over a missing-count copy.
            unknown_ids.difference_update(explicit_ids)

        original_update(actual_platform, content_files, queue)
        if actual_platform != "bili":
            return

        items = queue.get("items") or {}

        for identifier in explicit_zero_ids:
            item = items.get(identifier)
            if not isinstance(item, dict):
                continue
            item["visible_comment_count"] = 0
            item["queue_signal"] = "explicit_zero_comment_count"
            item["comment_count_unknown"] = False

        for identifier in unknown_ids:
            item = items.get(identifier)
            if not isinstance(item, dict):
                continue
            visible = int(item.get("visible_comment_count") or 0)
            if visible > 0 and not bool(item.get("comment_count_unknown")):
                item["queue_signal"] = "visible_comment_count"
                item["comment_count_unknown"] = False
                continue
            item["visible_comment_count"] = 1
            item["queue_signal"] = "bili_unknown_comment_count"
            item["comment_count_unknown"] = True

        for identifier in explicit_ids - explicit_zero_ids:
            item = items.get(identifier)
            if not isinstance(item, dict):
                continue
            if int(item.get("visible_comment_count") or 0) > 0:
                item["queue_signal"] = "visible_comment_count"
                item["comment_count_unknown"] = False

    crawler_runner._update_queue_from_content = update_bili
    setattr(crawler_runner, marker, True)
