from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.normalizer import normalize_record


PLATFORMS = {"xhs", "dy", "ks", "bili", "wb", "toutiao", "zhihu", "wechat_mp", "wechat_channels"}
PROVINCE_ALIASES = [
    ("内蒙古", "内蒙古"), ("广西", "广西"), ("西藏", "西藏"), ("宁夏", "宁夏"), ("新疆", "新疆"),
    ("香港", "香港"), ("澳门", "澳门"), ("北京", "北京"), ("天津", "天津"), ("上海", "上海"),
    ("重庆", "重庆"), ("河北", "河北"), ("山西", "山西"), ("辽宁", "辽宁"), ("吉林", "吉林"),
    ("黑龙江", "黑龙江"), ("江苏", "江苏"), ("浙江", "浙江"), ("安徽", "安徽"), ("福建", "福建"),
    ("江西", "江西"), ("山东", "山东"), ("河南", "河南"), ("湖北", "湖北"), ("湖南", "湖南"),
    ("广东", "广东"), ("海南", "海南"), ("四川", "四川"), ("贵州", "贵州"), ("云南", "云南"),
    ("陕西", "陕西"), ("甘肃", "甘肃"), ("青海", "青海"), ("台湾", "台湾"),
]


def _read_jsonl(path: Path):
    try:
        with path.open("r", encoding="utf-8-sig") as f:
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
    except Exception:
        return


def _canonical_public_region(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    for prefix in ("IP属地：", "IP属地:", "IP属地", "来自：", "来自:", "来自"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    for needle, province in PROVINCE_ALIASES:
        if needle in text:
            return province
    if len(text) <= 16 and not any(ch.isdigit() for ch in text):
        return text
    return ""


def _prepare_region_aliases(raw: dict) -> dict:
    out = dict(raw)
    candidates = [
        raw.get("ip_location"), raw.get("ip_region"), raw.get("ip_label"),
        raw.get("province"), raw.get("province_name"), raw.get("user_province"),
        raw.get("author_province"), raw.get("region"), raw.get("region_name"),
        raw.get("comment_ip_location"), raw.get("user_ip_location"),
    ]
    for parent_key in ("user", "author", "creator", "member"):
        parent = raw.get(parent_key)
        if isinstance(parent, dict):
            candidates.extend([
                parent.get("ip_location"), parent.get("ip_region"), parent.get("ip_label"),
                parent.get("ip_address"), parent.get("province"), parent.get("province_name"), parent.get("region"),
            ])
    reply_control = raw.get("reply_control")
    if isinstance(reply_control, dict):
        candidates.append(reply_control.get("location"))
    for value in candidates:
        region = _canonical_public_region(value)
        if region:
            out["ip_location"] = region
            break
    return out


def _load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _data_root(config: dict, platform: str) -> Path:
    base = Path(str(config["data_root"]))
    if base.name.endswith(f"_{platform}"):
        return base
    return base.parent / f"{base.name}_{platform}"


def _raw_jsonl_files(root: Path) -> list[Path]:
    candidates: list[Path] = []
    raw_runs = root / "raw_runs"
    if raw_runs.exists():
        candidates.extend(raw_runs.rglob("*.jsonl"))
    for p in root.glob("*.jsonl"):
        if p.parent.name not in {"classified", "outbox", "status"}:
            candidates.append(p)
    return sorted({p.resolve() for p in candidates if p.is_file()})


def _regionish_key_names(obj, prefix: str = "", depth: int = 0, out: set[str] | None = None) -> set[str]:
    if out is None:
        out = set()
    if depth > 3 or not isinstance(obj, dict):
        return out
    for key, value in obj.items():
        name = str(key)
        full = f"{prefix}.{name}" if prefix else name
        low = name.lower()
        if any(token in low for token in ("ip", "region", "province", "location")):
            out.add(full)
        if isinstance(value, dict):
            _regionish_key_names(value, full, depth + 1, out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Backfill coarse public IP-location labels from already-collected raw JSONL into classified results."
    )
    ap.add_argument("--platform", required=True, choices=sorted(PLATFORMS))
    ap.add_argument("--config", default="config/monitoring.local.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = _load_config(Path(args.config).resolve())
    platform = args.platform
    root = _data_root(cfg, platform)
    classified_path = root / "classified" / "classified_results.jsonl"

    if not root.exists():
        raise SystemExit(f"Data root not found: {root}")
    if not classified_path.exists():
        raise SystemExit(f"Classified results not found: {classified_path}")

    raw_files = _raw_jsonl_files(root)
    if not raw_files:
        raise SystemExit(f"No raw JSONL files found under: {root}")

    region_by_key: dict[str, str] = {}
    regionish_keys: set[str] = set()
    raw_rows = 0
    raw_rows_with_region = 0

    for path in raw_files:
        for raw in _read_jsonl(path) or []:
            raw_rows += 1
            regionish_keys.update(_regionish_key_names(raw))
            prepared = _prepare_region_aliases(raw)
            rec = normalize_record(prepared, source_file=path.name, platform_hint=platform)
            if not rec:
                continue
            region = str(rec.get("ip_location") or "").strip()
            if not region:
                continue
            raw_rows_with_region += 1
            key = str(rec.get("dedupe_key") or "").strip()
            if key:
                region_by_key[key] = region

    classified_rows = list(_read_jsonl(classified_path) or [])
    before = sum(1 for r in classified_rows if str(r.get("ip_location") or "").strip())
    updated = 0
    matched_with_region = 0

    for row in classified_rows:
        key = str(row.get("dedupe_key") or "").strip()
        region = region_by_key.get(key, "")
        if not region:
            continue
        matched_with_region += 1
        old = str(row.get("ip_location") or "").strip()
        if old != region:
            row["ip_location"] = region
            updated += 1

    after = sum(1 for r in classified_rows if str(r.get("ip_location") or "").strip())
    content_regions = Counter()
    comment_regions = Counter()
    all_regions = Counter()
    for row in classified_rows:
        region = str(row.get("ip_location") or "").strip()
        if not region:
            continue
        all_regions[region] += 1
        if str(row.get("record_type") or "") == "comment":
            comment_regions[region] += 1
        else:
            content_regions[region] += 1

    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "platform": platform,
        "data_root": str(root),
        "raw_jsonl_files": len(raw_files),
        "raw_rows_scanned": raw_rows,
        "raw_rows_with_public_region": raw_rows_with_region,
        "classified_records": len(classified_rows),
        "classified_region_records_before": before,
        "classified_region_records_after": after,
        "classified_records_updated": updated,
        "matched_classified_records_with_region": matched_with_region,
        "regions": dict(all_regions.most_common()),
        "content_regions": dict(content_regions.most_common()),
        "comment_regions": dict(comment_regions.most_common()),
        "regionish_raw_keys_seen": sorted(regionish_keys),
        "dry_run": bool(args.dry_run),
    }

    if not args.dry_run and updated:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = classified_path.with_name(classified_path.name + f".bak_region_{stamp}")
        backup.write_bytes(classified_path.read_bytes())
        tmp = classified_path.with_suffix(classified_path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for row in classified_rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        tmp.replace(classified_path)
        report["backup"] = str(backup)

    status_dir = root / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    output = status_dir / "region_backfill_latest.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if after == 0:
        if not regionish_keys:
            print("\nNo public region value can be recovered from these legacy raw files: the collector version that created them did not persist any region/location field. Install the final region-aware collector and use a new collection cycle; do not keep retrying backfill on the same legacy files.")
        else:
            print("\nNo public region value was recovered. Inspect regionish_raw_keys_seen; a platform-specific alias may still need mapping.")
    elif args.dry_run:
        print("\nDry-run only: classified_results.jsonl was not changed.")
    else:
        print("\nRegion backfill completed. Keep the GitHub sync window running; the node summary should expose regions/content_regions/comment_regions on its next sync.")


if __name__ == "__main__":
    main()
