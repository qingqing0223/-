from __future__ import annotations

SUPPORTED = {"xhs", "bili", "wb", "toutiao", "zhihu"}


def install_unknown_comment_count_fallback(platform: str) -> None:
    """Queue content only when comment count is genuinely unavailable.

    Explicit public count=0 means the content currently has zero comments and
    must NOT be converted into a synthetic positive queue signal.

    A synthetic queue signal is used only when all known comment-count fields
    are absent/empty from the source row.
    """
    if platform not in SUPPORTED:
        return

    import monitor.crawler_runner as crawler_runner

    marker = f"_promotion_week_unknown_comment_fallback_{platform}"
    if getattr(crawler_runner, marker, False):
        return

    original_update = crawler_runner._update_queue_from_content

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

    def update_with_unknown_count_fallback(
        actual_platform: str,
        content_files,
        queue: dict,
    ) -> None:
        # Inspect source rows BEFORE applying the fallback so that explicit
        # zero and genuinely missing counts remain distinguishable.
        explicit_ids: set[str] = set()
        explicit_zero_ids: set[str] = set()
        unknown_ids: set[str] = set()

        if actual_platform == platform:
            for row in crawler_runner._iter_jsonl(content_files):
                identifier = crawler_runner._detail_identifier(
                    actual_platform,
                    row,
                )
                if not identifier:
                    continue

                if has_explicit_comment_count(row):
                    explicit_ids.add(identifier)
                    if crawler_runner._visible_comment_count(row) <= 0:
                        explicit_zero_ids.add(identifier)
                else:
                    unknown_ids.add(identifier)

            # Explicit platform data always wins over a missing-count copy of
            # the same content returned through another search keyword.
            unknown_ids.difference_update(explicit_ids)

        original_update(actual_platform, content_files, queue)

        if actual_platform != platform:
            return

        items = queue.get("items") or {}

        # Explicit count=0 is a real observation. Remove any older synthetic
        # queue signal that may have incorrectly turned it into 1.
        for identifier in explicit_zero_ids:
            item = items.get(identifier)
            if not isinstance(item, dict):
                continue

            item["visible_comment_count"] = 0
            item["queue_signal"] = "explicit_zero_comment_count"
            item["comment_count_unknown"] = False

        # Only genuinely missing counts receive the bounded probe signal.
        for identifier in unknown_ids:
            item = items.get(identifier)
            if not isinstance(item, dict):
                continue

            visible = int(item.get("visible_comment_count") or 0)

            # Preserve a previously observed real positive count.
            if visible > 0 and not bool(item.get("comment_count_unknown")):
                item["queue_signal"] = "visible_comment_count"
                item["comment_count_unknown"] = False
                continue

            item["visible_comment_count"] = 1
            item["queue_signal"] = f"{platform}_unknown_comment_count"
            item["comment_count_unknown"] = True

        # Normalize positive explicitly observed counts.
        for identifier in explicit_ids - explicit_zero_ids:
            item = items.get(identifier)
            if not isinstance(item, dict):
                continue
            if int(item.get("visible_comment_count") or 0) > 0:
                item["queue_signal"] = "visible_comment_count"
                item["comment_count_unknown"] = False

    crawler_runner._update_queue_from_content = update_with_unknown_count_fallback
    setattr(crawler_runner, marker, True)
