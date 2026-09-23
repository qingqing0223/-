from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor.bilibili_policy import is_bilibili_campaign_relevant


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _iter_jsonl(path: Path):
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if isinstance(row, dict):
                    yield row
    except Exception:
        return


def _platform_root(cfg: dict) -> Path:
    base = Path(cfg["data_root"])
    if base.name.endswith("_bili"):
        return base
    return base.parent / f"{base.name}_bili"


def _latest_cycle(root: Path) -> Path | None:
    raw = root / "raw_runs"
    if not raw.exists():
        return None
    cycles = sorted((p for p in raw.iterdir() if p.is_dir()), key=lambda p: p.name)
    return cycles[-1] if cycles else None


def _first(row: dict, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _region(row: dict) -> str:
    value = _first(row, "ip_location", "ip_region", "ip_label", "region", "province")
    if value in (None, ""):
        reply_control = row.get("reply_control")
        if isinstance(reply_control, dict):
            value = _first(reply_control, "location", "ip_location", "ip_region")
    if value in (None, ""):
        member = row.get("member")
        if isinstance(member, dict):
            value = _first(member, "ip_location", "ip_region", "region", "province")
    text = str(value or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", text):
        return ""
    if re.fullmatch(r"[0-9a-fA-F:]{6,}", text):
        return ""
    if re.search(r"\d+\.\d+\s*[,，]\s*\d+\.\d+", text):
        return ""
    return text


def _parse_time(value, default_tz=None):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or str(value).isdigit():
        try:
            ts = float(value)
            if ts > 1e12:
                ts /= 1000.0
            return datetime.fromtimestamp(ts).astimezone()
        except Exception:
            return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None and default_tz is not None:
            dt = dt.replace(tzinfo=default_tz)
        return dt
    except Exception:
        return None


def _comment_time(row: dict, start):
    return _parse_time(
        _first(row, "publish_time", "create_time", "ctime", "created_at", "time"),
        default_tz=(start.tzinfo if start else None),
    )


def _nested_capability_history(root: Path, max_cycles: int = 20) -> dict:
    raw_root = root / "raw_runs"
    if not raw_root.exists():
        return {
            "observed": False,
            "cycle": "",
            "nested_replies": 0,
            "parent_integrity_rate": 1.0,
        }

    cycles = sorted(
        (p for p in raw_root.iterdir() if p.is_dir()),
        key=lambda p: p.name,
        reverse=True,
    )[:max_cycles]

    for cycle in cycles:
        comment_rows = [
            row
            for p in sorted(cycle.rglob("*.jsonl"))
            if "comment" in p.name.lower()
            for row in (_iter_jsonl(p) or [])
        ]
        if not comment_rows:
            continue

        comment_ids = {
            str(_first(row, "comment_id", "rpid", "cid") or "").strip()
            for row in comment_rows
            if str(_first(row, "comment_id", "rpid", "cid") or "").strip()
        }
        nested = 0
        linked = 0
        orphan = 0
        for row in comment_rows:
            parent = str(
                _first(
                    row,
                    "parent_comment_id",
                    "parent_id",
                    "parent",
                    "parent_rpid",
                )
                or ""
            ).strip()
            if parent in {"", "0", "None", "null"}:
                continue
            nested += 1
            linked += 1
            if parent not in comment_ids:
                orphan += 1

        if nested > 0:
            integrity = round((linked - orphan) / nested, 4)
            return {
                "observed": True,
                "cycle": cycle.name,
                "nested_replies": nested,
                "parent_linked_replies": linked,
                "orphan_parent_links": orphan,
                "parent_integrity_rate": integrity,
            }

    return {
        "observed": False,
        "cycle": "",
        "nested_replies": 0,
        "parent_integrity_rate": 1.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect the latest Bilibili realtime cycle: SLA, comments, recency, hierarchy and public coarse IP-region.")
    ap.add_argument("--config", default=str(ROOT / "config" / "monitoring.local.json"))
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = _load(cfg_path)
    if not cfg:
        print(json.dumps({"ok": False, "error": "config_not_readable", "config": str(cfg_path)}, ensure_ascii=False, indent=2))
        return 2

    root = _platform_root(cfg)
    cycle = _latest_cycle(root)
    if cycle is None:
        print(json.dumps({"ok": False, "error": "no_bilibili_raw_cycle", "root": str(root)}, ensure_ascii=False, indent=2))
        return 3

    nested_history = _nested_capability_history(root)

    status = _load(root / "status" / "latest_status.json")
    run = (status.get("platform_runs") or [{}])[0]
    ingest = (status.get("ingest") or [{}])[0]

    jsonl = sorted(cycle.rglob("*.jsonl"))
    content_files = [p for p in jsonl if "content" in p.name.lower()]
    comment_files = [p for p in jsonl if "comment" in p.name.lower()]
    content_rows = [row for p in content_files for row in (_iter_jsonl(p) or [])]
    comment_rows = [row for p in comment_files for row in (_iter_jsonl(p) or [])]

    start = _parse_time(cfg.get("monitoring_start_time"))
    comment_ids = {
        str(_first(row, "comment_id", "rpid", "cid") or "").strip()
        for row in comment_rows
        if str(_first(row, "comment_id", "rpid", "cid") or "").strip()
    }

    first_level = 0
    nested = 0
    parent_linked = 0
    orphan = 0
    recent = 0
    regions = Counter()
    recent_regions = Counter()
    recent_first_level = 0
    recent_nested = 0

    for row in comment_rows:
        parent = str(_first(row, "parent_comment_id", "parent_id", "parent", "parent_rpid") or "").strip()
        is_nested = parent not in {"", "0", "None", "null"}
        if is_nested:
            nested += 1
            parent_linked += 1
            if parent not in comment_ids:
                orphan += 1
        else:
            first_level += 1

        region = _region(row)
        if region:
            regions[region] += 1

        dt = _comment_time(row, start)
        is_recent = bool(start is None or dt is None or dt >= start)
        if is_recent:
            recent += 1
            if is_nested:
                recent_nested += 1
            else:
                recent_first_level += 1
            if region:
                recent_regions[region] += 1

    parent_integrity = round((parent_linked - orphan) / nested, 4) if nested else 1.0
    region_count = sum(regions.values())

    required_content_fields = (
        "video_id",
        "title",
        "create_time",
        "creator_hash",
        "nickname",
        "video_play_count",
        "liked_count",
        "video_comment",
        "video_share_count",
        "video_favorite_count",
        "video_danmaku",
        "video_coin_count",
        "bvid",
        "category_name",
        "duration",
        "tags",
        "creator_public_id",
        "account_name",
        "creator_profile_url",
        "follower_count",
        "following_count",
    )
    content_schema_complete = bool(content_rows) and all(
        all(field in row for field in required_content_fields)
        for row in content_rows
    )
    publisher_metrics_present = any(
        row.get("follower_count") not in (None, "")
        and row.get("following_count") not in (None, "")
        for row in content_rows
    )
    nested_root_field_complete = all(
        (
            str(_first(row, "root_comment_id", "root_id", "root_rpid") or "").strip()
            not in {"", "0", "None", "null"}
        )
        for row in comment_rows
        if str(_first(
            row,
            "parent_comment_id",
            "parent_id",
            "parent",
            "parent_rpid",
        ) or "").strip() not in {"", "0", "None", "null"}
    )

    classified_path = root / "classified" / "classified_results.jsonl"
    classified_rows = list(_iter_jsonl(classified_path) or []) if classified_path.exists() else []
    classified_content = [
        row for row in classified_rows
        if str(row.get("record_type") or "") != "comment"
    ]
    classified_topic_clean = all(
        is_bilibili_campaign_relevant(row)
        for row in classified_content
    )

    expected_keywords = [
        "2026年民族团结进步宣传周",
        "首个民族团结进步宣传周",
        "促进民族团结进步，奋进伟大复兴征程",
        "民族团结进步倡议",
        "民族团结进步宣传周主场活动",
        "石榴花开——铸牢中华民族共同体意识",
    ]
    formal_scope_config = (
        str(cfg.get("monitoring_start_time") or "")
        == "2026-09-16T00:00:00+08:00"
        and list(cfg.get("keywords") or []) == expected_keywords
    )

    checks = {
        "crawler_success": str(run.get("state") or "") == "SUCCESS" and int(run.get("return_code") or 0) == 0,
        "realtime_cycle_within_300s": bool(status.get("realtime_cycle_within_target", False)),
        "content_present": len(content_rows) > 0,
        "comments_present": len(comment_rows) > 0,
        "recent_comments_present": recent > 0,
        "first_level_present": first_level > 0,
        "nested_replies_present_latest_cycle": nested > 0,
        "nested_parent_integrity_latest_cycle": parent_integrity == 1.0,
        "nested_capability_observed_recent_cycles": bool(nested_history.get("observed")),
        "nested_capability_parent_integrity": (
            float(nested_history.get("parent_integrity_rate") or 0.0) == 1.0
            if nested_history.get("observed")
            else False
        ),
        "public_coarse_ip_region_present": region_count > 0,
        "recent_comments_reached_ingest": int(ingest.get("classified_comment_records") or 0) > 0,
        "formal_scope_config": formal_scope_config,
        "content_schema_complete": content_schema_complete,
        "publisher_metrics_present": publisher_metrics_present,
        "nested_root_field_complete": nested_root_field_complete,
        "classified_topic_clean": classified_topic_clean,
    }

    # A quiet realtime cycle can legitimately have no nested replies among the
    # newest comments. Treat nested-comment support as a capability that may be
    # evidenced by a recent prior cycle, rather than requiring every single cycle
    # to contain a reply thread.
    structural_ok = all([
        checks["crawler_success"],
        checks["realtime_cycle_within_300s"],
        checks["content_present"],
        checks["comments_present"],
        checks["first_level_present"],
    ])
    full_ok = all([
        structural_ok,
        checks["recent_comments_present"],
        checks["recent_comments_reached_ingest"],
        checks["public_coarse_ip_region_present"],
        checks["nested_capability_observed_recent_cycles"],
        checks["nested_capability_parent_integrity"],
        checks["formal_scope_config"],
        checks["content_schema_complete"],
        checks["publisher_metrics_present"],
        checks["nested_root_field_complete"],
        checks["classified_topic_clean"],
    ])

    out = {
        "ok": full_ok,
        "structural_ok": structural_ok,
        "cycle": cycle.name,
        "root": str(root),
        "runtime": {
            "state": run.get("state"),
            "return_code": run.get("return_code"),
            "duration_seconds": run.get("duration_seconds"),
            "within_300s": status.get("realtime_cycle_within_target"),
        },
        "raw": {
            "content_rows": len(content_rows),
            "comment_rows": len(comment_rows),
            "first_level_comments": first_level,
            "nested_replies": nested,
            "parent_linked_replies": parent_linked,
            "orphan_parent_links": orphan,
            "parent_integrity_rate": parent_integrity,
            "comments_at_or_after_monitoring_start": recent,
            "recent_first_level_comments": recent_first_level,
            "recent_nested_replies": recent_nested,
            "public_coarse_ip_region_records": region_count,
            "public_coarse_ip_region_rate": round(region_count / len(comment_rows), 4) if comment_rows else 0.0,
            "regions": dict(regions.most_common()),
            "recent_regions": dict(recent_regions.most_common()),
            "content_files": [str(p) for p in content_files],
            "comment_files": [str(p) for p in comment_files],
            "required_content_fields": list(required_content_fields),
            "content_schema_complete": content_schema_complete,
            "publisher_metrics_present": publisher_metrics_present,
            "nested_root_field_complete": nested_root_field_complete,
        },
        "nested_capability_history": nested_history,
        "ingest": {
            "raw_comment_rows": ingest.get("raw_comment_rows", 0),
            "classified_comment_records": ingest.get("classified_comment_records", 0),
            "filtered_before_start_comment_records": ingest.get("filtered_before_start_comment_records", 0),
            "region_records": ingest.get("region_records", 0),
            "classification_degraded": ingest.get("classification_degraded", False),
        },
        "checks": checks,
        "note": "Public coarse platform-displayed region labels only; real network IP and precise location are rejected.",
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if full_ok else (4 if structural_ok else 5)


if __name__ == "__main__":
    raise SystemExit(main())
