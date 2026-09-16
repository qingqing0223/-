from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path

from monitor.ingest import _prepare_region_aliases
from pipeline.normalizer import normalize_record


PLATFORMS = {"xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu", "wechat_mp", "wechat_channels"}


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


def _load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _data_root(config: dict, platform: str) -> Path:
    base = Path(str(config["data_root"]))
    # run_single_platform.py uses one formal root per platform.
    if base.name.endswith(f"_{platform}"):
        return base
    return base.parent / f"{base.name}_{platform}"


def _raw_jsonl_files(root: Path) -> list[Path]:
    candidates: list[Path] = []
    raw_runs = root / "raw_runs"
    if raw_runs.exists():
        candidates.extend(raw_runs.rglob("*.jsonl"))
    # Compatibility with earlier runs that may have written JSONL directly below the platform root.
    for p in root.glob("*.jsonl"):
        if p.parent.name not in {"classified", "outbox", "status"}:
            candidates.append(p)
    # Keep deterministic ordering and remove duplicates.
    return sorted({p.resolve() for p in candidates if p.is_file()})


def _regionish_key_names(obj, prefix: str = "", depth: int = 0, out: set[str] | None = None) -> set[str]:
    if out is None:
        out = set()
    if depth > 2 or not isinstance(obj, dict):
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
        description="Backfill public IP-location/region labels from already-collected raw JSONL into classified results."
    )
    ap.add_argument("--platform", required=True, choices=sorted(PLATFORMS))
    ap.add_argument("--config", default="config/monitoring.local.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    config_path = Path(args.config).resolve()
    cfg = _load_config(config_path)
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
    raw_region_counts = Counter()
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
                raw_region_counts[region] += 1

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
        print("\nNo public region value was recovered. Check regionish_raw_keys_seen above; the raw collector may not have persisted IP-location labels.")
    elif args.dry_run:
        print("\nDry-run only: classified_results.jsonl was not changed.")
    else:
        print("\nRegion backfill completed. Keep the GitHub sync window running; the node summary should expose regions/content_regions/comment_regions on its next sync.")


if __name__ == "__main__":
    main()
