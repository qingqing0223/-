from __future__ import annotations

"""Validated Kuaishou discovery-query plan.

Search queries are deliberately discovery inputs only. Their type is retained
for audit and never used as a topic-inclusion allow-list.
"""

from collections import Counter


QUERY_TYPES = {"core", "alias", "typo_supplement", "combination", "association_supplement"}
FORBIDDEN_STANDALONE_QUERIES = {"宣传片", "主题片", "主场活动", "民族团结", "主题宣传"}


def build_kuaishou_query_plan(entries: object) -> list[dict[str, str]]:
    if not isinstance(entries, list):
        raise ValueError("kuaishou_query_catalog must be a list")
    plan: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"kuaishou_query_catalog[{index}] must be an object")
        query = str(entry.get("query") or "").strip()
        query_type = str(entry.get("query_type") or "").strip()
        if not query:
            raise ValueError(f"kuaishou_query_catalog[{index}] has an empty query")
        if query_type not in QUERY_TYPES:
            raise ValueError(f"unsupported Kuaishou query_type: {query_type!r}")
        if query in FORBIDDEN_STANDALONE_QUERIES:
            raise ValueError(f"overly broad Kuaishou query is forbidden by itself: {query}")
        if query not in seen:
            seen.add(query)
            plan.append({"query": query, "query_type": query_type})
    if not plan:
        raise ValueError("kuaishou_query_catalog must contain at least one query")
    return plan


def apply_kuaishou_query_plan(cfg: dict) -> dict:
    if not any(str(row.get("code") or "") == "ks" for row in cfg.get("platforms") or []):
        return cfg
    entries = cfg.get("kuaishou_query_catalog")
    if entries is None:
        return cfg
    plan = build_kuaishou_query_plan(entries)
    cfg["kuaishou_query_catalog"] = plan
    cfg["keywords"] = [row["query"] for row in plan]
    cfg["kuaishou_query_plan_summary"] = {
        "query_count": len(plan),
        "by_type": dict(sorted(Counter(row["query_type"] for row in plan).items())),
        "search_terms_are_discovery_inputs_not_relevance_allowlist": True,
    }
    return cfg


def query_catalog_by_query(entries: object) -> dict[str, str]:
    if not entries:
        return {}
    return {row["query"]: row["query_type"] for row in build_kuaishou_query_plan(entries)}
