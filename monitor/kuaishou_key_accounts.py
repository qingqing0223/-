from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pipeline.io_utils import read_json, write_json


def _clean(value) -> str:
    return str(value or "").strip()


def _name_key(value) -> str:
    return re.sub(r"[\s·•._\-—]+", "", _clean(value)).casefold()


def _canonical_url(value) -> str:
    text = _clean(value)
    if not text:
        return ""
    try:
        parts = urlsplit(text)
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))
    except Exception:
        return text.rstrip("/")


def load_kuaishou_key_accounts(path: Path) -> dict:
    data = read_json(path, {"platform": "ks", "accounts": [], "key_content_ids": []})
    if str(data.get("platform") or "ks") != "ks":
        raise ValueError(f"Kuaishou key-account config has unexpected platform: {path}")
    return data


def match_kuaishou_key_account(record: dict, registry: dict) -> dict:
    author_id = _clean(record.get("author_id"))
    author_name = _name_key(record.get("author"))
    profile_url = _canonical_url(record.get("author_profile_url"))
    id_matches = []
    url_matches = []
    name_matches = []

    for item in registry.get("accounts") or []:
        if not item.get("enabled", True):
            continue
        ids = {_clean(x) for x in (item.get("account_ids") or []) if _clean(x)}
        urls = {_canonical_url(x) for x in (item.get("profile_urls") or []) if _canonical_url(x)}
        names = {
            _name_key(x) for x in [item.get("canonical_name"), *(item.get("aliases") or [])]
            if _name_key(x)
        }
        if author_id and author_id in ids:
            id_matches.append(item)
        if profile_url and profile_url in urls:
            url_matches.append(item)
        if author_name and author_name in names:
            name_matches.append(item)

    verified = []
    for item in [*id_matches, *url_matches]:
        if item not in verified:
            verified.append(item)
    if len(verified) == 1:
        item = verified[0]
        return {
            "is_key_monitor_account": True,
            "key_account_match_status": "verified",
            "key_account_match_basis": "stable_account_id" if id_matches else "verified_profile_url",
            "key_account_canonical_name": _clean(item.get("canonical_name")),
            "key_account_category": _clean(item.get("category")),
            "key_account_institution": _clean(item.get("institution")),
        }
    if len(verified) > 1:
        return {
            "is_key_monitor_account": False,
            "key_account_match_status": "ambiguous_verified_identifier",
            "key_account_match_basis": "conflicting_registry_entries",
        }
    if len(name_matches) == 1:
        item = name_matches[0]
        return {
            "is_key_monitor_account": False,
            "key_account_match_status": "name_candidate_unverified",
            "key_account_match_basis": "exact_configured_name_or_alias_only",
            "key_account_canonical_name": _clean(item.get("canonical_name")),
            "key_account_category": _clean(item.get("category")),
            "key_account_institution": _clean(item.get("institution")),
        }
    if len(name_matches) > 1:
        return {
            "is_key_monitor_account": False,
            "key_account_match_status": "ambiguous_name_candidate",
            "key_account_match_basis": "multiple_configured_name_matches",
        }
    return {
        "is_key_monitor_account": False,
        "key_account_match_status": "no_match",
        "key_account_match_basis": "none",
    }


def enrich_kuaishou_key_account_records(
    records: list[dict], registry: dict, key_content_state_path: Path,
) -> dict:
    state = read_json(key_content_state_path, {"content_ids": []})
    key_content_ids = {_clean(x) for x in state.get("content_ids") or [] if _clean(x)}
    key_content_ids.update(
        _clean(x) for x in registry.get("key_content_ids") or [] if _clean(x)
    )

    verified_accounts = 0
    name_candidates = 0
    for record in records:
        match = match_kuaishou_key_account(record, registry)
        record.update(match)
        if match["is_key_monitor_account"]:
            verified_accounts += 1
        elif match["key_account_match_status"] == "name_candidate_unverified":
            name_candidates += 1
        if record.get("record_type") != "comment" and match["is_key_monitor_account"]:
            content_id = _clean(record.get("content_id"))
            if content_id:
                key_content_ids.add(content_id)

    key_contents = 0
    key_comments = 0
    for record in records:
        content_id = _clean(record.get("content_id"))
        is_key_content = bool(content_id and content_id in key_content_ids)
        record["is_key_monitor_content"] = is_key_content
        if record.get("record_type") == "comment":
            record["is_key_monitor_comment"] = is_key_content
            key_comments += int(is_key_content)
        else:
            key_contents += int(is_key_content)

    write_json(key_content_state_path, {"content_ids": sorted(key_content_ids)})
    return {
        "verified_key_account_records": verified_accounts,
        "unverified_name_candidate_records": name_candidates,
        "key_content_records": key_contents,
        "key_comment_records": key_comments,
        "known_key_content_ids": len(key_content_ids),
    }
