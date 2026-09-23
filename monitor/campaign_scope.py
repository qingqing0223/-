from __future__ import annotations

"""Promotion-week search expansion and strict topic-admission policy.

Policy principle: search broad, admit strict.

The configured direct keywords are the stable, human-reviewed core. Runtime
search can additionally include aliases, common misspellings, paired queries,
and related-concept recovery queries. A broad search hit is NOT automatically
valid monitoring data; the returned content text must independently satisfy the
admission rules below.
"""

from dataclasses import dataclass
import re


POLICY_VERSION = "promotion_week_search_v2_20260923"

CORE_KEYWORDS = (
    "民族团结进步宣传周",
    "2026年民族团结进步宣传周",
    "首个民族团结进步宣传周",
    "民族团结进步宣传周启动",
    "民族团结进步宣传周活动",
    "民族团结进步宣传周主场活动",
    "2026年民族团结进步宣传周主场活动",
    "民族团结进步宣传周主题宣传片",
    "民族团结进步倡议",
    "民族团结进步倡议书",
    "促进民族团结进步，奋进伟大复兴征程",
)

ALIASES = (
    "民族团结宣传周",
    "民族宣传周",
    "团结进步宣传周",
    "民族团结倡议",
    "团结进步倡议",
)

TYPO_RECOVERY_TERMS = (
    "民族团结进取宣传周",
)

COMBINATION_QUERIES = (
    "民族团结进步 宣传周",
    "民族团结进步 主场活动",
    "民族团结进步 主题宣传片",
    "民族团结 宣传周",
    "民族团结进步 主题活动",
    "民族团结进步 宣传教育",
)

RELATED_RECOVERY_QUERIES = (
    "民族团结进步促进法 宣传周",
    "民族团结进步促进法 2026",
    "铸牢中华民族共同体意识 宣传周",
    "铸牢中华民族共同体意识 2026",
    "铸牢中华民族共同体意识 主场活动",
    "石榴花开 宣传周",
    "石榴花开 2026",
    "石榴花开 主场活动",
    "石榴花开 9月21日",
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

_OTHER_PUBLICITY_WEEKS = (
    "网络安全宣传周",
    "国家网络安全宣传周",
    "推广普通话宣传周",
    "节能宣传周",
    "宪法宣传周",
    "绿色出行宣传周",
)

_RELATED_CONCEPTS = (
    "民族团结进步促进法",
    "铸牢中华民族共同体意识",
    "石榴花开",
)

_EVENT_CONTEXT_MARKERS = (
    "2026",
    "首个",
    "宣传周",
    "主场活动",
    "主题宣传片",
    "9月21日",
    "9月22日",
    "9月23日",
    "9月24日",
    "9月25日",
    "9月26日",
    "9月27日",
    "9月21日至27日",
    "9月21日-27日",
    "9月21—27日",
    "9月21-27日",
)

_OLDER_YEAR_RE = re.compile(r"20(?:1\d|2[0-5])年?")


@dataclass(frozen=True)
class CampaignDecision:
    valid: bool
    reason: str
    matched_keywords: tuple[str, ...]


def _dedupe(items) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def all_search_queries() -> list[str]:
    """Return the complete reviewed discovery query set."""
    return _dedupe([
        *CORE_KEYWORDS,
        *ALIASES,
        *TYPO_RECOVERY_TERMS,
        *COMBINATION_QUERIES,
        *RELATED_RECOVERY_QUERIES,
    ])


def select_realtime_queries(
    queries: list[str] | tuple[str, ...],
    *,
    supplemental_count: int = 5,
    bucket: int = 0,
) -> list[str]:
    """Keep all core queries every cycle and rotate broad recovery queries.

    This prevents the broad-search policy from turning one realtime cycle into
    an unbounded crawl. Historical/backfill mode should use all_search_queries().
    """
    available = _dedupe(queries)
    core = [q for q in CORE_KEYWORDS if q in available]
    supplemental = [q for q in available if q not in set(core)]
    if not supplemental or supplemental_count <= 0:
        return core or available

    count = min(max(1, int(supplemental_count)), len(supplemental))
    start = (max(0, int(bucket)) * count) % len(supplemental)
    rotated = supplemental[start:] + supplemental[:start]
    return _dedupe(core + rotated[:count])


def _compact(value) -> str:
    return (
        "".join(str(value or "").split())
        .replace("，", ",")
        .replace("：", ":")
        .replace("—", "-")
        .replace("－", "-")
    )


def campaign_text(row: dict) -> str:
    if not isinstance(row, dict):
        return ""
    return _compact(" ".join(str(row.get(key) or "") for key in _TEXT_FIELDS))


def matched_campaign_terms(row: dict) -> tuple[str, ...]:
    text = campaign_text(row)
    if not text:
        return ()
    terms = []
    for term in (*CORE_KEYWORDS, *ALIASES, *TYPO_RECOVERY_TERMS, *_RELATED_CONCEPTS):
        if _compact(term) in text:
            terms.append(term)
    return tuple(_dedupe(terms))


def _has_current_event_context(text: str) -> bool:
    return any(_compact(marker) in text for marker in _EVENT_CONTEXT_MARKERS)


def _mentions_only_older_year(text: str) -> bool:
    if "2026" in text:
        return False
    return bool(_OLDER_YEAR_RE.search(text))


def evaluate_campaign_relevance(row: dict) -> CampaignDecision:
    """Strictly decide whether a broad search hit belongs in formal monitoring."""
    if not isinstance(row, dict):
        return CampaignDecision(False, "not_a_record", ())

    text = campaign_text(row)
    matched = matched_campaign_terms(row)
    if not text:
        return CampaignDecision(False, "empty_topic_text", matched)

    # Common false positives explicitly called out by the collection protocol.
    if "民族团结进步宣传月" in text and "民族团结进步宣传周" not in text:
        return CampaignDecision(False, "promotion_month_not_promotion_week", matched)

    if any(_compact(other) in text for other in _OTHER_PUBLICITY_WEEKS):
        if "民族团结进步宣传周" not in text and "民族团结宣传周" not in text:
            return CampaignDecision(False, "other_publicity_week", matched)

    # A current post can discuss an old campaign. Do not admit an explicitly
    # older-year campaign unless the same content also anchors itself to 2026.
    if _mentions_only_older_year(text) and (
        "民族团结进步宣传周" in text
        or "民族团结宣传周" in text
        or "团结进步宣传周" in text
    ):
        return CampaignDecision(False, "historical_campaign_year", matched)

    # The reviewed core is direct enough to admit from the content itself.
    for phrase in CORE_KEYWORDS:
        if _compact(phrase) in text:
            return CampaignDecision(True, "core_keyword_in_content", matched)

    # Two reasonably specific aliases retain the campaign object "宣传周".
    if "民族团结宣传周" in text or "团结进步宣传周" in text:
        return CampaignDecision(True, "promotion_week_alias_in_content", matched)

    # Broader aliases/typos are search recovery only unless the content also
    # supplies an independent current-event anchor.
    broad_aliases = (
        "民族宣传周",
        "民族团结倡议",
        "团结进步倡议",
        "民族团结进取宣传周",
    )
    if any(alias in text for alias in broad_aliases) and _has_current_event_context(text):
        return CampaignDecision(True, "alias_plus_event_context", matched)

    # Combination rules: broad words are never sufficient in isolation.
    if "民族团结进步" in text and "主场活动" in text and _has_current_event_context(text):
        return CampaignDecision(True, "combined_main_event", matched)
    if "民族团结进步" in text and "主题宣传片" in text and _has_current_event_context(text):
        return CampaignDecision(True, "combined_theme_video", matched)
    if "民族团结进步" in text and "主题活动" in text and _has_current_event_context(text):
        return CampaignDecision(True, "combined_theme_activity", matched)
    if "民族团结进步" in text and "宣传教育" in text and (
        "2026" in text or "宣传周" in text or "9月2" in text
    ):
        return CampaignDecision(True, "combined_publicity_education", matched)

    # Related concepts are explicitly recovery terms only. They require an
    # event/date/main-venue anchor and never become valid merely because the
    # search query that found them contained a campaign term.
    if any(concept in text for concept in _RELATED_CONCEPTS) and _has_current_event_context(text):
        return CampaignDecision(True, "related_concept_plus_event_context", matched)

    return CampaignDecision(False, "broad_hit_without_campaign_evidence", matched)


def is_campaign_relevant(row: dict) -> bool:
    return evaluate_campaign_relevance(row).valid
