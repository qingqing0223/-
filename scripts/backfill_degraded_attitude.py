from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.classifier import classify_records


PLATFORMS = {"xhs", "dy", "wb", "ks", "bili", "toutiao", "zhihu"}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _platform_root(cfg: dict, platform: str) -> Path:
    base = Path(str(cfg["data_root"]))
    if base.name.endswith("_" + platform):
        return base
    return base.parent / f"{base.name}_{platform}"


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                yield row


def _is_degraded(row: dict) -> bool:
    if row.get("classification_ok") is False:
        return True
    if str(row.get("classification_state") or "").strip().lower() == "degraded":
        return True
    if str(row.get("status") or "").strip().lower() == "unclassified":
        return True
    return False


def _write_atomic(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".attitude-backfill.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill degraded attitude classifications without recrawling platform data.")
    ap.add_argument("--platform", required=True, choices=sorted(PLATFORMS))
    ap.add_argument("--config", default=str(ROOT / "config" / "monitoring.local.json"))
    ap.add_argument("--batch-size", type=int, default=20)
    ap.add_argument("--limit", type=int, default=0, help="0 means all degraded rows")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = _load_json(cfg_path)
    root = _platform_root(cfg, args.platform)
    classified_path = root / "classified" / "classified_results.jsonl"
    if not classified_path.exists():
        print(json.dumps({
            "ok": False,
            "error": "classified_output_not_found",
            "path": str(classified_path),
        }, ensure_ascii=False, indent=2))
        return 2

    rows = list(_iter_jsonl(classified_path))
    degraded_indices = [i for i, row in enumerate(rows) if _is_degraded(row)]
    if args.limit > 0:
        degraded_indices = degraded_indices[:args.limit]

    if args.dry_run or not degraded_indices:
        print(json.dumps({
            "ok": True,
            "platform": args.platform,
            "classified_output": str(classified_path),
            "total_rows": len(rows),
            "degraded_rows_selected": len(degraded_indices),
            "dry_run": bool(args.dry_run),
            "changed": 0,
        }, ensure_ascii=False, indent=2))
        return 0

    batch_size = max(1, int(args.batch_size))
    recovered = 0
    still_degraded = 0
    attempted = 0
    updated_rows = list(rows)
    errors = set()

    for start in range(0, len(degraded_indices), batch_size):
        indices = degraded_indices[start:start + batch_size]
        batch = [rows[i] for i in indices]
        classified = classify_records(batch, concurrency=max(1, int(cfg.get("classifier_concurrency", 4))))
        attempted += len(indices)
        for idx, new_row in zip(indices, classified):
            if new_row.get("classification_ok") is True:
                updated_rows[idx] = new_row
                recovered += 1
            else:
                still_degraded += 1
                err = str(new_row.get("classification_error") or "").strip()
                if err:
                    errors.add(err[:600])

    # Never rewrite the file if the provider is still unavailable and nothing recovered.
    if recovered > 0:
        backup = classified_path.with_suffix(classified_path.suffix + ".before-attitude-backfill")
        if not backup.exists():
            backup.write_bytes(classified_path.read_bytes())
        _write_atomic(classified_path, updated_rows)

    result = {
        "ok": recovered == attempted and attempted > 0,
        "platform": args.platform,
        "classified_output": str(classified_path),
        "total_rows": len(rows),
        "degraded_rows_selected": len(degraded_indices),
        "attempted": attempted,
        "recovered": recovered,
        "still_degraded": still_degraded,
        "changed_file": recovered > 0,
        "errors": sorted(errors)[:3],
        "note": (
            "This operation reclassifies already normalized records only; it does not crawl the platform again. "
            "If the external model is still unavailable, the production classified file is left unchanged."
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
