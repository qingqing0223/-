from __future__ import annotations

import json
from pathlib import Path

from .campaign_scope import POLICY_VERSION, all_search_queries


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def load_keyword_pack(path: Path, include_unverified: bool = False) -> tuple[list[str], dict]:
    """Load verified multilingual search terms from a JSON keyword pack.

    Unverified terms are ignored by default so the realtime crawler never starts
    searching a machine-generated or unreviewed translation by accident.
    """
    if not path.exists():
        return [], {"ok": False, "error": f"keyword pack not found: {path}"}

    data = json.loads(path.read_text(encoding="utf-8"))
    languages = data.get("languages") or {}
    keywords = []
    loaded = {}
    skipped = {}
    for language, spec in languages.items():
        if not isinstance(spec, dict) or not spec.get("enabled", True):
            continue
        verified = bool(spec.get("verified", False))
        terms = _dedupe(spec.get("keywords") or [])
        if not verified and not include_unverified:
            skipped[language] = {"reason": "unverified", "keywords": len(terms)}
            continue
        if not terms:
            skipped[language] = {"reason": "empty", "keywords": 0}
            continue
        keywords.extend(terms)
        loaded[language] = len(terms)

    return _dedupe(keywords), {
        "ok": True,
        "path": str(path),
        "loaded": loaded,
        "skipped": skipped,
        "keyword_count": len(_dedupe(keywords)),
    }


def apply_keyword_pack(cfg: dict, config_path: Path) -> dict:
    pack_name = str(cfg.get("keyword_pack_file") or "").strip()
    if not pack_name:
        return cfg

    pack_path = Path(pack_name)
    if not pack_path.is_absolute():
        candidate = config_path.parent / pack_path
        if candidate.exists():
            pack_path = candidate
        else:
            pack_path = Path.cwd() / pack_path

    extra, meta = load_keyword_pack(
        pack_path,
        include_unverified=bool(cfg.get("include_unverified_keywords", False)),
    )
    base = _dedupe(list(cfg.get("keywords") or []))
    campaign_extra = []
    campaign_meta = {
        "enabled": False,
        "policy_version": "",
        "search_query_count": 0,
    }
    if bool(cfg.get("campaign_search_expand", False)):
        campaign_extra = all_search_queries()
        campaign_meta = {
            "enabled": True,
            "policy_version": POLICY_VERSION,
            "search_query_count": len(campaign_extra),
        }

    cfg["keywords"] = _dedupe(base + campaign_extra + extra)
    cfg["keyword_pack_status"] = {
        **meta,
        "campaign_search": campaign_meta,
        "effective_keyword_count": len(cfg["keywords"]),
    }
    return cfg
