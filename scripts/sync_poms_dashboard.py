#!/usr/bin/env python3
"""Build a GitHub Pages dashboard snapshot from the read-only POMS APIs.

The POMS base URL is intentionally read only from POMS_URL or --base-url.
It must not be embedded in browser code or committed to the repository.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "yuqing-v1/03_live_system/web/assets/poms-dashboard.json"
CHINA_TIMEZONE = timezone(timedelta(hours=8))

TABLE_PATHS = {
    "platforms": "overall_and_platform_distribution_statistics",
    "regions": "regional_distribution_statistics",
    "top_contents": "top_10_key_communication_contents",
    "trend": "overall_communication_trend",
    "classification": "public_opinion_classification_result_details?page=1&page_size=500",
    "attitudes": "public_opinion_attitude_statistics_by_platform?page=1&page_size=500",
    "problem_types": "problematic_data_type_statistics?page=1&page_size=500",
    "risk_items": "important_problematic_data_details?page=1&page_size=500",
}


def number(value: Any) -> int | float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0
    return int(parsed) if parsed.is_integer() else parsed


def text(value: Any) -> str:
    return "" if value is None else str(value)


def iso_now() -> str:
    return datetime.now(CHINA_TIMEZONE).isoformat(timespec="seconds")


def fetch_rows(base_url: str, path: str, timeout: int) -> list[dict[str, Any]]:
    url = f"{base_url.rstrip('/')}/api/v1/tables/{path}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"POMS read failed for {path}: {type(exc).__name__}") from exc
    if not isinstance(data, list):
        raise RuntimeError(f"POMS returned a non-list payload for {path}")
    return [row for row in data if isinstance(row, dict)]


def date_part(value: Any) -> str:
    return text(value)[:10]


def hour_part(value: Any) -> str:
    raw = text(value)
    return raw[:13] if len(raw) >= 13 else raw


def build_snapshot(source: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    platform_source = source["platforms"]
    region_source = source["regions"]
    total = sum(number(row.get("total_information_count")) for row in platform_source)
    publish_count = sum(number(row.get("published_content_count")) for row in platform_source)
    comment_count = sum(number(row.get("comment_and_reply_count")) for row in platform_source)

    platforms = [
        {
            "name": text(row.get("platform")) or "未标注平台",
            "total": number(row.get("total_information_count")),
            "support": 0,
            "neutral": 0,
            "nonSupport": 0,
            "supportRate": 0,
        }
        for row in platform_source
    ]
    provinces = [
        {
            "name": text(row.get("region")) or "未标注地区",
            "value": number(row.get("total_information_count")),
            "total": number(row.get("total_information_count")),
            "support": 0,
        }
        for row in region_source
    ]

    daily_trend: dict[str, int | float] = defaultdict(int)
    trend_hourly = []
    for row in source["trend"]:
        timestamp = text(row.get("statistical_time"))
        value = number(row.get("total_information_count"))
        heat = number(row.get("total_interaction_count"))
        day = date_part(timestamp)
        if day:
            daily_trend[day] += value
        trend_hourly.append(
            {
                "hour": hour_part(timestamp),
                "label": timestamp[11:16] if len(timestamp) >= 16 else timestamp,
                "date": day,
                "value": value,
                "heat": heat,
                "publishedCount": number(row.get("published_content_count")),
                "commentCount": number(row.get("comment_and_reply_count")),
            }
        )
    trend_hourly.sort(key=lambda row: row["hour"])

    top_contents = [
        {
            "platform": text(row.get("platform")) or "未标注平台",
            "account": text(row.get("publishing_account")) or "未标注发布者",
            "title": text(row.get("content_title_or_summary")),
            "date": date_part(row.get("published_at")),
            "likes": number(row.get("like_count")),
            "comments": number(row.get("comment_count")),
            "shares": number(row.get("repost_or_share_count")),
            "favorites": number(row.get("favorite_count")),
            "url": text(row.get("original_url")),
        }
        for row in source["top_contents"]
    ]

    supportive = sum(number(row.get("supportive_count")) for row in source["attitudes"])
    neutral = sum(number(row.get("neutral_count")) for row in source["attitudes"])
    problematic = sum(number(row.get("problematic_count")) for row in source["attitudes"])
    non_support = [
        {"name": text(row.get("problem_type")) or "未分类问题", "value": number(row.get("total"))}
        for row in source["problem_types"]
    ]
    risk_items = [
        {
            "platform": text(row.get("platform")) or "未标注平台",
            "account": text(row.get("account")) or "未标注账号",
            "text": text(row.get("content_summary")),
            "date": date_part(row.get("published_at")),
            "attitude": "问题",
            "issueCategory": text(row.get("problem_type")),
            "likes": number(row.get("like_count")),
            "comments": number(row.get("comment_count")),
            "shares": number(row.get("repost_or_share_count")),
            "heat": sum(
                number(row.get(key))
                for key in ("view_or_play_count", "like_count", "comment_count", "repost_or_share_count")
            ),
            "url": text(row.get("original_url")),
        }
        for row in source["risk_items"]
    ]
    quotes = [
        {
            "platform": text(row.get("platform")) or "未标注平台",
            "text": text(row.get("core_viewpoint_or_original_text")),
            "attitude": text(row.get("final_category")) or text(row.get("primary_category")),
            "issueCategory": text(row.get("secondary_category")),
            "account": text(row.get("data_id")),
            "source": "POMS 分类结果",
        }
        for row in source["classification"]
    ]

    return {
        "source": {"mode": "poms-snapshot", "label": "POMS 后端快照", "generatedAt": iso_now()},
        "generatedAt": iso_now(),
        "phase": {"label": "民族团结进步宣传周", "statsStart": "", "includeHistory": False, "phaseOnly": False},
        "topStats": {
            "totalOpinions": total,
            "totalOpinionsLabel": "累计信息数",
            "detectedPlatformCount": sum(1 for row in platforms if row["total"] > 0),
            "detectedPlatformCountAll": len(platforms),
            "detectedRegionCount": sum(1 for row in provinces if row["total"] > 0),
            "supportCount": supportive,
            "nonSupport": problematic,
        },
        "stats": {
            "total": total,
            "publishCount": publish_count,
            "commentCount": comment_count,
            "support": supportive,
            "neutral": neutral,
            "nonSupport": problematic,
            "regionCount": sum(1 for row in provinces if row["total"] > 0),
            "platformCount": sum(1 for row in platforms if row["total"] > 0),
            "platformCountAll": len(platforms),
        },
        "platforms": platforms,
        "platformDetail": platforms,
        "regions": provinces,
        "provinces": provinces,
        "focusRegions": [],
        "trend": [{"date": day, "value": value} for day, value in sorted(daily_trend.items())],
        "trendHourly": trend_hourly,
        "hotTop": top_contents,
        "quotes": quotes,
        "attitude": {
            "macro": [
                {"name": "支持认可", "value": supportive},
                {"name": "中性信息", "value": neutral},
                {"name": "参与建议", "value": 0},
                {"name": "问题", "value": problematic},
            ],
            "detail": non_support,
        },
        "nonSupport": non_support,
        "riskItems": risk_items,
        "keyAccounts": [],
        "languagePlatform": [],
        "unknownPlatforms": [],
        "live": None,
    }


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("POMS_URL", ""))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    if not args.base_url:
        parser.error("POMS_URL or --base-url is required")

    source = {name: fetch_rows(args.base_url, path, args.timeout) for name, path in TABLE_PATHS.items()}
    snapshot = build_snapshot(source)
    write_json_atomic(args.output, snapshot)
    print(json.dumps({"ok": True, "output": str(args.output), "row_counts": {k: len(v) for k, v in source.items()}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
