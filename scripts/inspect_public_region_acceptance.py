from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor.ingest import _canonical_public_region


def _read_jsonl(path: Path):
    try:
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
    except Exception:
        return


def _platform_roots(cfg: dict, platform: str) -> list[Path]:
    base = Path(cfg["data_root"])
    candidates = [
        base.parent / f"{base.name}_{platform}",
        base.parent / f"{base.name}_multilingual_{platform}",
    ]
    return [p for p in candidates if p.exists()]


def _latest_raw_cycle(root: Path) -> Path | None:
    raw_root = root / "raw_runs"
    if not raw_root.exists():
        return None
    cycles = sorted((p for p in raw_root.iterdir() if p.is_dir()), key=lambda p: p.name)
    return cycles[-1] if cycles else None


def _summarize_files(paths: list[Path]) -> dict:
    rows = 0
    field_rows = 0
    value_rows = 0
    regions: dict[str, int] = {}
    files = []
    for path in paths:
        file_rows = 0
        file_fields = 0
        file_values = 0
        for row in _read_jsonl(path) or []:
            rows += 1
            file_rows += 1
            if "ip_location" in row:
                field_rows += 1
                file_fields += 1
            region = _canonical_public_region(row.get("ip_location"))
            if region:
                value_rows += 1
                file_values += 1
                regions[region] = regions.get(region, 0) + 1
        files.append({
            "name": path.name,
            "rows": file_rows,
            "ip_location_field_rows": file_fields,
            "public_region_value_rows": file_values,
        })
    if not paths:
        state = "NO_RAW_FILES"
    elif rows and field_rows == 0:
        state = "MISSING_IP_LOCATION_FIELD"
    elif value_rows > 0:
        state = "PUBLIC_REGION_VALUES_PRESENT"
    else:
        state = "FIELD_PRESENT_NO_PUBLIC_REGION_VALUE"
    return {
        "state": state,
        "rows": rows,
        "ip_location_field_rows": field_rows,
        "ip_location_field_rate": round(field_rows / rows, 4) if rows else 0.0,
        "public_region_value_rows": value_rows,
        "public_region_value_rate": round(value_rows / rows, 4) if rows else 0.0,
        "regions": dict(sorted(regions.items(), key=lambda kv: (-kv[1], kv[0]))),
        "files": files,
    }


def inspect(config_path: Path, platform: str) -> dict:
    cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
    roots = _platform_roots(cfg, platform)
    per_root = []
    overall_state = "NO_DATA_ROOT"

    for root in roots:
        cycle = _latest_raw_cycle(root)
        if cycle is None:
            per_root.append({
                "data_root": str(root),
                "cycle": "",
                "content": _summarize_files([]),
                "comment": _summarize_files([]),
            })
            continue

        jsonl = sorted(cycle.rglob("*.jsonl"))
        content_files = [p for p in jsonl if "content" in p.name.lower() and "comment" not in p.name.lower()]
        comment_files = [p for p in jsonl if "comment" in p.name.lower()]
        content = _summarize_files(content_files)
        comment = _summarize_files(comment_files)
        per_root.append({
            "data_root": str(root),
            "cycle": cycle.name,
            "content": content,
            "comment": comment,
        })

    states = [
        section["state"]
        for root in per_root
        for section in (root["content"], root["comment"])
    ]
    if "MISSING_IP_LOCATION_FIELD" in states:
        overall_state = "PATCH_NOT_EFFECTIVE_IN_LATEST_RAW"
    elif "PUBLIC_REGION_VALUES_PRESENT" in states:
        overall_state = "PUBLIC_REGION_VALUES_PRESENT"
    elif "FIELD_PRESENT_NO_PUBLIC_REGION_VALUE" in states:
        overall_state = "PATCH_FIELD_PRESENT_PLATFORM_RETURNED_NO_VALUE"
    elif per_root:
        overall_state = "NO_LATEST_RAW_FILES"

    return {
        "ok": overall_state not in {"PATCH_NOT_EFFECTIVE_IN_LATEST_RAW", "NO_DATA_ROOT"},
        "platform": platform,
        "overall_state": overall_state,
        "privacy": "platform_displayed_coarse_region_only_no_real_ip_no_precise_location",
        "roots": per_root,
        "interpretation": {
            "PUBLIC_REGION_VALUES_PRESENT": "Patch is effective and the platform returned at least one public coarse region value.",
            "PATCH_FIELD_PRESENT_PLATFORM_RETURNED_NO_VALUE": "ip_location is being persisted, but this latest raw cycle exposed no public region value.",
            "PATCH_NOT_EFFECTIVE_IN_LATEST_RAW": "Latest raw rows exist but do not contain the ip_location field; update/patch deployment must be checked.",
            "NO_LATEST_RAW_FILES": "No content/comment JSONL was produced in the latest raw cycle.",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect the latest raw cycle for public coarse IP-region persistence.")
    ap.add_argument("--platform", required=True, choices=["xhs", "dy", "ks", "bili", "wb", "toutiao", "zhihu"])
    ap.add_argument("--config", default=".\\config\\monitoring.local.json")
    args = ap.parse_args()
    try:
        result = inspect(Path(args.config).resolve(), args.platform)
    except Exception as exc:
        result = {
            "ok": False,
            "platform": args.platform,
            "overall_state": "INSPECTOR_ERROR",
            "error": f"{type(exc).__name__}: {exc}",
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
