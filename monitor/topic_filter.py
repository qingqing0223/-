"""Topic relevance helpers for the 2026 promotion-week monitor."""

_CAMPAIGN_PHRASES = (
    "\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65\u5ba3\u4f20\u5468",
    "\u4fc3\u8fdb\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65\uff0c\u594b\u8fdb\u4f1f\u5927\u590d\u5174\u5f81\u7a0b",
)

_TEXT_FIELDS = (
    "title",
    "desc",
    "description",
    "body",
    "content",
    "context",
    "tags",
    "tag_text",
    "asr_text",
    "ocr_text",
)


def is_campaign_relevant(row: dict) -> bool:
    """Conservative topic gate for formal campaign collection."""
    text = " ".join(
        str(row.get(key) or "")
        for key in _TEXT_FIELDS
    )
    compact = "".join(text.split())

    return any(
        "".join(phrase.split()) in compact
        for phrase in _CAMPAIGN_PHRASES
    )
