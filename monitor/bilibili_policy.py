from __future__ import annotations

"""Bilibili-specific wrapper around the shared promotion-week scope policy.

Bilibili uses broad discovery terms, but formal collection only admits content
whose own public text satisfies the shared strict-admission rules. Search-keyword
provenance alone is never sufficient.
"""

from monitor.campaign_scope import (
    CampaignDecision,
    campaign_text,
    evaluate_campaign_relevance,
    is_campaign_relevant,
    matched_campaign_terms,
)


def bilibili_campaign_text(row: dict) -> str:
    return campaign_text(row)


def evaluate_bilibili_campaign_relevance(row: dict) -> CampaignDecision:
    return evaluate_campaign_relevance(row)


def is_bilibili_campaign_relevant(row: dict) -> bool:
    return is_campaign_relevant(row)


def bilibili_matched_campaign_terms(row: dict) -> tuple[str, ...]:
    return matched_campaign_terms(row)
