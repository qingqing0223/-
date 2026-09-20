from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Iterable

from pipeline.io_utils import read_jsonl


TABLE5_FIELDS = (
    "account_id",
    "platform",
    "account_name",
    "profile_url",
    "account_type",
    "followers",
    "following",
    "region",
    "organization",
    "is_key_account",
    "related_post_count",
    "views",
    "likes",
    "comments",
    "shares",
    "favorites",
    "total_interactions",
    "collected_at",
)


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def _latest_classified_rows(path: Path) -> list[dict]:
    latest: dict[str, dict] = {}
    if not path.exists():
        return []
    for row in read_jsonl(path):
        if not isinstance(row, dict):
            continue
        key = _clean(row.get("dedupe_key"))
        if not key:
            continue
        latest[key] = row
    return list(latest.values())


def _load_profile_rows(files: Iterable[Path]) -> list[dict]:
    rows: list[dict] = []
    for path in files:
        if "account_info" not in path.name.lower():
            continue
        for row in read_jsonl(path):
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _match_profile(account: dict, profiles: list[dict]) -> dict:
    creator_id = _clean(account.get("creator_id"))
    name = _clean(account.get("name"))
    for row in reversed(profiles):
        if creator_id and creator_id in {
            _clean(row.get("creator_id")),
            _clean(row.get("account_id")),
        }:
            return row
    for row in reversed(profiles):
        if name and name == _clean(row.get("account_name")):
            return row
    return {}


def _match_content(account: dict, rows: list[dict]) -> list[dict]:
    creator_id = _clean(account.get("creator_id"))
    name = _clean(account.get("name"))
    matched = []
    for row in rows:
        if _clean(row.get("record_type")) == "comment":
            continue
        author_id = _clean(row.get("author_id"))
        author = _clean(row.get("author"))
        if creator_id and author_id == creator_id:
            matched.append(row)
        elif name and author == name:
            matched.append(row)
    return matched


def build_table5_account_rows(
    platform: str,
    configured_accounts: list[dict],
    classified_path: Path,
    raw_files: Iterable[Path] = (),
) -> list[dict]:
    """Build Tech Design V3 Table 5 rows.

    Table 5 contains:
    1. every publisher actually appearing in valid collected content;
    2. configured key accounts, even if they have not published matching content yet.

    Publicly unavailable fields stay empty and are never estimated.
    """
    latest_rows = _latest_classified_rows(classified_path)
    profiles = _load_profile_rows(raw_files)
    collected_at = datetime.now().astimezone().isoformat(timespec="seconds")

    accounts: list[dict] = []

    # First preserve configured/key monitored accounts.
    for account in configured_accounts:
        if _clean(account.get("platform")) != platform:
            continue
        item = dict(account)
        # Entries from the configured key-account catalog are key accounts
        # unless explicitly marked otherwise.
        item["is_key_account"] = bool(account.get("is_key_account", True))
        accounts.append(item)

    def find_existing(creator_id: str, name: str):
        for item in accounts:
            item_id = _clean(
                item.get("creator_id")
                or item.get("account_id")
                or item.get("author_id")
            )
            item_name = _clean(
                item.get("name")
                or item.get("account_name")
                or item.get("author")
            )

            if creator_id and item_id and creator_id == item_id:
                return item
            if name and item_name and name == item_name:
                return item
        return None

    # Then add every real publisher appearing in valid Table-1 content.
    for row in latest_rows:
        if _clean(row.get("record_type")) == "comment":
            continue

        creator_id = _clean(row.get("author_id"))
        name = _clean(row.get("author"))

        if not creator_id and not name:
            continue

        existing = find_existing(creator_id, name)

        if existing is not None:
            if creator_id and not _clean(existing.get("creator_id")):
                existing["creator_id"] = creator_id
            if name and not _clean(existing.get("name")):
                existing["name"] = name
            if (
                _clean(row.get("author_profile_url"))
                and not _clean(existing.get("profile_url"))
            ):
                existing["profile_url"] = _clean(row.get("author_profile_url"))
            if (
                _clean(row.get("ip_location"))
                and not _clean(existing.get("ip_location"))
            ):
                existing["ip_location"] = _clean(row.get("ip_location"))
            continue

        accounts.append({
            "platform": platform,
            "creator_id": creator_id,
            "name": name,
            "profile_url": _clean(row.get("author_profile_url")),
            "ip_location": _clean(row.get("ip_location")),
            "account_type": "",
            "organization": "",
            "region": "",
            "is_key_account": False,
        })

    output: list[dict] = []

    for account in accounts:
        profile = _match_profile(account, profiles)
        posts = _match_content(account, latest_rows)

        likes = sum(int(row.get("likes") or 0) for row in posts)
        comments = sum(int(row.get("comments") or 0) for row in posts)
        shares = sum(int(row.get("shares") or 0) for row in posts)
        favorites = sum(int(row.get("favorites") or 0) for row in posts)
        views = sum(int(row.get("views") or 0) for row in posts)

        account_id = (
            _clean(profile.get("account_id"))
            or _clean(account.get("account_id"))
            or _clean(account.get("creator_id"))
        )

        account_name = (
            _clean(profile.get("account_name"))
            or _clean(account.get("name"))
        )

        profile_url = (
            _clean(profile.get("profile_url"))
            or _clean(account.get("profile_url"))
        )

        account_type = (
            _clean(account.get("account_type"))
            or _clean(profile.get("account_type_hint"))
        )

        organization = (
            _clean(account.get("organization"))
            or _clean(profile.get("organization"))
            or _clean(profile.get("auth_info"))
        )

        # "????" and "IP??" are kept as separate fields.
        region = (
            _clean(profile.get("region"))
            or _clean(account.get("region"))
        )

        ip_location = (
            _clean(profile.get("ip_location"))
            or _clean(account.get("ip_location"))
        )

        # If the profile endpoint did not provide IP location,
        # retain a publicly exposed location from the publisher's post.
        if not ip_location:
            for post in reversed(posts):
                candidate = _clean(post.get("ip_location"))
                if candidate:
                    ip_location = candidate
                    break

        followers = profile.get("followers")
        if followers in ("", None):
            followers = account.get("followers")

        following = profile.get("following")
        if following in ("", None):
            following = account.get("following")

        output.append({
            "account_id": account_id,
            "platform": platform,
            "account_name": account_name,
            "profile_url": profile_url,
            "account_type": account_type,
            "ip_location": ip_location,
            "followers": followers if followers not in ("", None) else None,
            "following": following if following not in ("", None) else None,
            "region": region,
            "organization": organization,
            "is_key_account": bool(account.get("is_key_account", False)),
            "related_post_count": len(posts),
            "views": views,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "favorites": favorites,
            "total_interactions": likes + comments + shares + favorites,
            "collected_at": collected_at,
            "public_metrics_only": True,
        })

    return output

def write_table5_account_snapshots(root: Path, rows: list[dict]) -> dict:
    """Write a latest snapshot plus one replaceable daily snapshot.

    Tech Design V3 requires Table 5 to be updated daily. During acceptance runs
    this avoids creating a new permanent row every five minutes.
    """
    account_root = root / "account_info"
    daily_root = account_root / "daily"
    daily_root.mkdir(parents=True, exist_ok=True)

    latest_path = account_root / "latest_accounts.json"
    latest_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    day = datetime.now().astimezone().strftime("%Y-%m-%d")
    daily_path = daily_root / f"{day}.json"
    daily_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "latest": str(latest_path),
        "daily": str(daily_path),
        "rows": len(rows),
    }
