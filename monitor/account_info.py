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


def _wb_public_count(value):
    """Normalize public Weibo count strings without estimating missing data."""
    if value in (None, ""):
        return None

    text = str(value).strip().replace(",", "")
    unit_10k = chr(0x4E07)

    try:
        if text.endswith(unit_10k):
            return int(float(text[:-1]) * 10000)
        if text.lower().endswith("w"):
            return int(float(text[:-1]) * 10000)
        if text.lower().endswith("k"):
            return int(float(text[:-1]) * 1000)
        return int(float(text))
    except (TypeError, ValueError):
        return None


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


def _load_key_account_catalog() -> dict[str, str]:
    """Return exact account-name -> Tech Design V3 type mapping."""
    path = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "key_accounts.v3.catalog.json"
    )

    if not path.exists():
        return {}

    try:
        data = json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception:
        return {}

    mapping: dict[str, str] = {}

    for category in data.get("categories") or []:
        account_type = _clean(
            category.get("account_type")
        )

        for name in category.get("accounts") or []:
            name = _clean(name)

            if name and account_type:
                mapping[name] = account_type

    return mapping


def _discover_accounts(
    platform: str,
    rows: list[dict],
) -> list[dict]:
    """Discover actual publishing accounts from monitored posts."""
    found: dict[str, dict] = {}

    for row in rows:
        if _clean(row.get("platform")) != platform:
            continue

        if _clean(row.get("record_type")) == "comment":
            continue

        account_id = _clean(row.get("author_id"))
        account_name = _clean(row.get("author"))

        if not account_id and not account_name:
            continue

        key = (
            f"id:{account_id}"
            if account_id
            else f"name:{account_name}"
        )

        current = found.get(key)

        if current is None:
            found[key] = {
                "platform": platform,
                "creator_id": account_id,
                "account_id": account_id,
                "name": account_name,
            }
        elif (
            not _clean(current.get("name"))
            and account_name
        ):
            current["name"] = account_name

    return list(found.values())


def _merge_account_sources(
    platform: str,
    discovered: list[dict],
    configured: list[dict],
) -> list[dict]:
    """Merge observed WB accounts with optional configured metadata."""
    output: list[dict] = []
    by_id: dict[str, dict] = {}
    by_name: dict[str, dict] = {}

    def upsert(item: dict) -> None:
        if _clean(item.get("platform")) != platform:
            return

        account_id = (
            _clean(item.get("creator_id"))
            or _clean(item.get("account_id"))
        )

        name = (
            _clean(item.get("name"))
            or _clean(item.get("account_name"))
        )

        existing = None

        if account_id:
            existing = by_id.get(account_id)

        if existing is None and name:
            candidate = by_name.get(name)

            if candidate is not None:
                candidate_id = (
                    _clean(candidate.get("creator_id"))
                    or _clean(candidate.get("account_id"))
                )

                # Do not merge distinct known IDs merely because
                # display names happen to be identical.
                if (
                    not account_id
                    or not candidate_id
                    or candidate_id == account_id
                ):
                    existing = candidate

        if existing is None:
            existing = dict(item)
            output.append(existing)
        else:
            for key, value in item.items():
                if value not in (None, ""):
                    existing[key] = value

        final_id = (
            _clean(existing.get("creator_id"))
            or _clean(existing.get("account_id"))
        )

        final_name = (
            _clean(existing.get("name"))
            or _clean(existing.get("account_name"))
        )

        if final_id:
            by_id[final_id] = existing

        if final_name:
            by_name[final_name] = existing

    for item in discovered:
        upsert(item)

    for item in configured:
        upsert(item)

    return output


def build_table5_account_rows(
    platform: str,
    configured_accounts: list[dict],
    classified_path: Path,
    raw_files: Iterable[Path] = (),
) -> list[dict]:
    """Build Tech Design V3 Table 5 rows from public profile/post metadata.

    Unavailable public fields stay null/empty; they are never estimated.
    """
    latest_rows = _latest_classified_rows(classified_path)
    profiles = _load_profile_rows(raw_files)

    # Preserve the existing configured-account behavior for every
    # other platform. WB additionally includes every observed publisher.
    accounts = configured_accounts
    catalog: dict[str, str] = {}

    if platform == "wb":
        catalog = _load_key_account_catalog()
        discovered = _discover_accounts(
            platform,
            latest_rows,
        )
        accounts = _merge_account_sources(
            platform,
            discovered,
            configured_accounts,
        )

    collected_at = datetime.now().astimezone().isoformat(timespec="seconds")
    output: list[dict] = []

    for account in accounts:
        if _clean(account.get("platform")) != platform:
            continue
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
            or _clean(account.get("account_name"))
        )
        profile_url = (
            _clean(profile.get("profile_url"))
            or _clean(account.get("profile_url"))
        )
        catalog_type = (
            catalog.get(account_name, "")
            if platform == "wb"
            else ""
        )

        account_type = (
            catalog_type
            or _clean(account.get("account_type"))
            or _clean(profile.get("account_type_hint"))
        )
        organization = (
            _clean(account.get("organization"))
            or _clean(profile.get("organization"))
            or _clean(profile.get("auth_info"))
        )
        region = _clean(profile.get("region")) or _clean(account.get("region"))

        followers = profile.get("followers")
        if followers in ("", None):
            followers = account.get("followers")

        following = profile.get("following")
        if following in ("", None):
            following = account.get("following")

        if platform == "wb":
            followers = _wb_public_count(followers)
            following = _wb_public_count(following)

            # Only a numeric public WB ID can safely form this URL.
            if account_id.isdigit():
                profile_url = (
                    f"https://m.weibo.cn/u/{account_id}"
                )

        output.append({
            "account_id": account_id,
            "platform": platform,
            "account_name": account_name,
            "profile_url": profile_url,
            "account_type": account_type,
            "followers": followers if followers not in ("", None) else None,
            "following": following if following not in ("", None) else None,
            "region": region,
            "organization": organization,
            "is_key_account": (
                bool(catalog_type)
                or bool(account.get("is_key_account", False))
            ) if platform == "wb" else bool(
                account.get("is_key_account", True)
            ),
            "related_post_count": len(posts),
            "views": None if platform == "wb" else views,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "favorites": None if platform == "wb" else favorites,
            "total_interactions": (
                likes
                + comments
                + shares
                + (0 if platform == "wb" else favorites)
            ),
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
