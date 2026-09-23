"""Topic relevance gate for the 2026 ethnic-unity promotion-week monitor.

Search broadly, admit strictly.
Search keyword alone is never sufficient evidence.
"""

from datetime import datetime, timezone, timedelta

_STRONG_PHRASES = (
    "\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65\u5ba3\u4f20\u5468",
    "2026\u5e74\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65\u5ba3\u4f20\u5468",
    "\u9996\u4e2a\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65\u5ba3\u4f20\u5468",
    "\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65\u5ba3\u4f20\u5468\u542f\u52a8",
    "\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65\u5ba3\u4f20\u5468\u6d3b\u52a8",
    "\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65\u5ba3\u4f20\u5468\u4e3b\u573a\u6d3b\u52a8",
    "2026\u5e74\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65\u5ba3\u4f20\u5468\u4e3b\u573a\u6d3b\u52a8",
    "\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65\u5ba3\u4f20\u5468\u4e3b\u9898\u5ba3\u4f20\u7247",
    "\u4fc3\u8fdb\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65,\u594b\u8fdb\u4f1f\u5927\u590d\u5174\u5f81\u7a0b",
)

_ALIAS_PHRASES = (
    "\u6c11\u65cf\u56e2\u7ed3\u5ba3\u4f20\u5468",
    "\u6c11\u65cf\u5ba3\u4f20\u5468",
    "\u56e2\u7ed3\u8fdb\u6b65\u5ba3\u4f20\u5468",
    "\u6c11\u65cf\u56e2\u7ed3\u5021\u8bae",
    "\u56e2\u7ed3\u8fdb\u6b65\u5021\u8bae",
    "\u6c11\u65cf\u56e2\u7ed3\u8fdb\u53d6\u5ba3\u4f20\u5468",
)

_ASSOCIATED_TERMS = (
    "\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65\u4fc3\u8fdb\u6cd5",
    "\u94f8\u7262\u4e2d\u534e\u6c11\u65cf\u5171\u540c\u4f53\u610f\u8bc6",
    "\u77f3\u69b4\u82b1\u5f00",
)

_CURRENT_CONTEXT = (
    "2026\u5e74",
    "\u9996\u4e2a",
    "9\u670821\u65e5",
    "9\u670822\u65e5",
    "9\u670821\u65e5\u81f327\u65e5",
    "9\u670821\u65e5\u81f39\u670827\u65e5",
    "\u4e3b\u573a\u6d3b\u52a8",
    "\u4e3b\u9898\u5ba3\u4f20\u7247",
)

_EXCLUDE_PHRASES = (
    "\u7f51\u7edc\u5b89\u5168\u5ba3\u4f20\u5468",
    "\u56fd\u5bb6\u7f51\u7edc\u5b89\u5168\u5ba3\u4f20\u5468",
    "\u63a8\u5e7f\u666e\u901a\u8bdd\u5ba3\u4f20\u5468",
    "\u8282\u80fd\u5ba3\u4f20\u5468",
    "\u80bf\u7624\u9632\u6cbb\u5ba3\u4f20\u5468",
    "\u5baa\u6cd5\u5ba3\u4f20\u5468",
    "\u7eff\u8272\u51fa\u884c\u5ba3\u4f20\u5468",
)

_TEXT_FIELDS = (
    "title", "desc", "description", "body", "content",
    "context", "tags", "tag_text", "asr_text", "ocr_text",
)

_TITLE_FIELDS = ("title", "context")

_OLD_YEARS = tuple(f"{y}\u5e74" for y in range(2016, 2026))


def _compact(value) -> str:
    return (
        "".join(str(value or "").split())
        .replace("\uff0c", ",")
        .replace("\uff1a", ":")
        .replace("\u2014", "-")
        .replace("\uff0d", "-")
    )


def _has(text, phrases):
    return any(_compact(x) in text for x in phrases)


def _row_in_campaign_window(row: dict) -> bool:
    """Return True when the content was published during 2026-09-21..27 Beijing time."""
    tz = timezone(timedelta(hours=8))

    for key in ("create_time", "publish_time", "pubdate"):
        value = row.get(key)

        if value in (None, ""):
            continue

        try:
            raw = str(value).strip()

            if raw.replace(".", "", 1).isdigit():
                ts = float(raw)

                if ts > 10_000_000_000:
                    ts /= 1000.0

                dt = datetime.fromtimestamp(ts, tz)

                if (
                    dt.year == 2026
                    and dt.month == 9
                    and 21 <= dt.day <= 27
                ):
                    return True

            if raw.startswith("2026-09-"):
                day = int(raw[8:10])
                if 21 <= day <= 27:
                    return True

        except Exception:
            continue

    return False


def is_campaign_relevant(row: dict) -> bool:
    text = _compact(" ".join(str(row.get(k) or "") for k in _TEXT_FIELDS))
    title = _compact(" ".join(str(row.get(k) or "") for k in _TITLE_FIELDS))

    # Historical material is excluded.
    if "2026\u5e74" not in title and any(y in title for y in _OLD_YEARS):
        return False

    # Promotion month != this promotion week.
    if "\u5ba3\u4f20\u6708" in title and not _has(title, _STRONG_PHRASES):
        return False

    # Other obvious campaign weeks.
    if _has(title, _EXCLUDE_PHRASES) and not _has(title, _STRONG_PHRASES):
        return False

    # Explicit target-campaign wording.
    if _has(text, _STRONG_PHRASES):
        return True

    has_context = (_has(text, _CURRENT_CONTEXT) or _row_in_campaign_window(row))

    # Alias / common expression / typo needs current-event context.
    if _has(text, _ALIAS_PHRASES) and has_context:
        return True

    # Combination retrieval rules.
    if "\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65" in text and "\u5ba3\u4f20\u5468" in text:
        return True

    if (
        "\u6c11\u65cf\u56e2\u7ed3" in text
        and "\u5ba3\u4f20\u5468" in text
        and has_context
    ):
        return True

    if (
        "\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65" in text
        and any(x in text for x in (
            "\u4e3b\u573a\u6d3b\u52a8",
            "\u4e3b\u9898\u5ba3\u4f20\u7247",
            "\u4e3b\u9898\u6d3b\u52a8",
            "\u5ba3\u4f20\u6559\u80b2",
        ))
        and has_context
    ):
        return True

    # Association terms are only supplementary evidence.
    if _has(text, _ASSOCIATED_TERMS):
        if any(x in text for x in (
            "\u5ba3\u4f20\u5468",
            "\u4e3b\u573a\u6d3b\u52a8",
            "9\u670821\u65e5",
            "9\u670822\u65e5",
            "9\u670821\u65e5\u81f327\u65e5",
        )):
            return True

    # Never admit a result only because of the search keyword.
    return False
