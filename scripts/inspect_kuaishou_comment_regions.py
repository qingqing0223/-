from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def platform_root(cfg: dict) -> Path:
    base = Path(cfg["data_root"])
    if base.name.endswith("_ks"):
        return base
    return base.parent / f"{base.name}_ks"


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                yield row


def coarse(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", text) or re.fullmatch(r"[0-9a-fA-F:]{6,}", text):
        return ""
    for prefix in ("IP属地：", "IP属地:", "IP属地", "来自：", "来自:", "来自"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text


def region(row: dict) -> str:
    for key in (
        "ip_location", "authorArea", "author_area", "authorRegion", "author_region",
        "ipLocation", "ip_region", "ipRegion", "region", "region_name", "province", "location", "area",
    ):
        value = row.get(key)
        if value not in (None, ""):
            got = coarse(value)
            if got:
                return got
    for key in ("author", "user", "userInfo", "user_info"):
        obj = row.get(key)
        if isinstance(obj, dict):
            got = region(obj)
            if got:
                return got
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify Kuaishou comment public IP-region restoration from the latest raw JSONL.")
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    cfg = load(Path(args.config).resolve())
    root = platform_root(cfg)
    raw_root = root / "raw_runs"
    cycles = sorted((p for p in raw_root.iterdir() if p.is_dir()), key=lambda p: p.name) if raw_root.exists() else []
    latest = cycles[-1] if cycles else None
    comment_files = sorted(latest.rglob("*comment*.jsonl")) if latest else []

    rows = []
    for path in comment_files:
        rows.extend(iter_jsonl(path))

    regions = Counter()
    first_level = 0
    nested = 0
    with_author_area_alias = 0
    for row in rows:
        parent = str(row.get("parent_comment_id") or row.get("root_comment_id") or "").strip()
        if parent:
            nested += 1
        else:
            first_level += 1
        if row.get("authorArea") or row.get("author_area"):
            with_author_area_alias += 1
        got = region(row)
        if got:
            regions[got] += 1

    result = {
        "ok": bool(rows) and sum(regions.values()) > 0,
        "platform": "ks",
        "data_root": str(root),
        "cycle": latest.name if latest else "",
        "comment_files": [str(p) for p in comment_files],
        "comment_rows": len(rows),
        "first_level_comments": first_level,
        "nested_replies": nested,
        "comment_public_ip_region_records": sum(regions.values()),
        "comment_public_ip_region_rate": round(sum(regions.values()) / len(rows), 4) if rows else 0.0,
        "comment_regions": dict(regions.most_common()),
        "authorArea_alias_records": with_author_area_alias,
        "acceptance": "PASS" if rows and regions else "FAIL_COMMENT_IP_REGION_NOT_RESTORED",
        "note": "Only platform-displayed coarse region labels are counted; real IP addresses are rejected.",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
