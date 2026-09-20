from __future__ import annotations

"""Zhihu key-account targeted search helpers.

The Tech Design V3 catalog contains account names, not trustworthy platform IDs.
This module therefore performs an explicit account-name search pass without
inventing creator IDs. Exact-name hits can later be marked as key accounts by the
submission exporter; active creator-mode crawling still requires a verified ID.
"""

import json
from pathlib import Path


DEFAULT_CATALOG = "config/key_accounts.v3.catalog.json"


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def load_key_account_search_terms(repo_root: Path, cfg: dict) -> list[str]:
    catalog_name = str(
        cfg.get("key_account_catalog") or DEFAULT_CATALOG
    ).strip()
    path = Path(catalog_name)
    if not path.is_absolute():
        path = repo_root / path

    catalog = _load_json(path)
    terms: list[str] = []
    seen: set[str] = set()

    for category in catalog.get("categories") or []:
        if not isinstance(category, dict):
            continue
        for raw_name in category.get("accounts") or []:
            canonical = str(raw_name or "").strip()
            if not canonical:
                continue

            # Composite catalog labels such as "新疆日报/石榴云" represent
            # alternative public-facing names. Search each alias separately.
            aliases = [
                part.strip()
                for part in canonical.replace("／", "/").split("/")
                if part.strip()
            ]
            if not aliases:
                aliases = [canonical]

            for term in aliases:
                if term not in seen:
                    seen.add(term)
                    terms.append(term)

    return terms


def build_key_account_search_config(cfg: dict, repo_root: Path) -> tuple[dict, list[str]]:
    terms = load_key_account_search_terms(repo_root, cfg)
    out = dict(cfg)
    out["keywords"] = terms

    # This pass is discovery-focused. Keep a small result cap per account-name
    # query so the 50+ catalog terms do not dominate the 15-minute cycle.
    cap = int(cfg.get("zhihu_key_account_discovery_max_notes_count", 5) or 5)
    out["zhihu_realtime_discovery_max_notes_count"] = max(1, min(cap, 10))

    # The process-local Zhihu scope policy was installed with the original six
    # campaign keywords before this config is used, so comment recovery still
    # admits only formally in-scope campaign content.
    out["realtime_mode"] = True
    out["get_comment"] = "yes"
    out["get_sub_comment"] = "yes"
    out["ingest_comments"] = True
    return out, terms
