from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor.ingest import ingest_and_classify


def _load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _platform_root(cfg: dict) -> Path:
    base = Path(str(cfg["data_root"]))
    if base.name.endswith("_ks"):
        return base
    return base.parent / f"{base.name}_ks"


def _latest_cycle(root: Path) -> Path:
    raw_root = root / "raw_runs"
    if not raw_root.exists():
        raise RuntimeError(f"raw_runs not found: {raw_root}")
    cycles = sorted((p for p in raw_root.iterdir() if p.is_dir()), key=lambda p: p.name)
    if not cycles:
        raise RuntimeError(f"no raw cycles under: {raw_root}")
    return cycles[-1]


def _input_files(cycle: Path) -> list[Path]:
    files = []
    for p in cycle.rglob("*.jsonl"):
        low = p.name.lower()
        if "content" in low or "comment" in low:
            files.append(p)
    return sorted(files)


def _region_counts(rows: list[dict], *, comments: bool) -> dict[str, int]:
    counter = Counter()
    for row in rows:
        is_comment = row.get("record_type") == "comment"
        if is_comment != comments:
            continue
        region = str(row.get("ip_location") or "").strip()
        if region:
            counter[region] += 1
    return dict(counter.most_common())


def _source_type_counts(rows: list[dict]) -> dict[str, int]:
    counter = Counter()
    for row in rows:
        if row.get("record_type") == "comment":
            continue
        label = str(row.get("source_type") or "").strip()
        if label:
            counter[label] += 1
    return dict(counter.most_common())


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Reprocess the latest Kuaishou raw JSONL without crawling again. "
            "Uses an isolated acceptance output/state so it does not change the production seen_ids state."
        )
    )
    ap.add_argument("--config", default=str(ROOT / "config" / "monitoring.ks-test.json"))
    args = ap.parse_args()

    config_path = Path(args.config).resolve()
    cfg = _load_config(config_path)
    root = _platform_root(cfg)
    cycle = _latest_cycle(root)
    files = _input_files(cycle)
    if not files:
        raise RuntimeError(f"no content/comment JSONL found under latest cycle: {cycle}")

    acceptance_dir = root / "acceptance"
    acceptance_dir.mkdir(parents=True, exist_ok=True)
    output_path = acceptance_dir / f"ks_reprocessed_{cycle.name}.jsonl"
    state_path = acceptance_dir / f"ks_reprocess_seen_{cycle.name}.json"
    summary_path = acceptance_dir / f"ks_reprocess_summary_{cycle.name}.json"
    latest_summary_path = acceptance_dir / "ks_reprocess_latest.json"

    # Acceptance reprocessing is intentionally deterministic: rebuild from the latest
    # raw cycle every time so a previous classifier outage/old normalizer state cannot
    # hide already collected records.
    output_path.unlink(missing_ok=True)
    state_path.unlink(missing_ok=True)

    summary = ingest_and_classify(
        "ks",
        files,
        state_path,
        output_path,
        concurrency=max(1, int(cfg.get("classifier_concurrency", 1))),
        monitoring_start_time=str(cfg.get("monitoring_start_time") or "2026-09-16T00:00:00+08:00"),
        monitoring_end_time=str(cfg.get("monitoring_end_time") or ""),
        enable_classification=False,
    )
    rows = summary.pop("_classified_rows", [])

    content_rows = [row for row in rows if row.get("record_type") != "comment"]
    comment_rows = [row for row in rows if row.get("record_type") == "comment"]
    first_level = [row for row in comment_rows if int(row.get("comment_level") or 0) == 1]
    nested = [row for row in comment_rows if int(row.get("comment_level") or 0) >= 2]
    linked = [row for row in nested if str(row.get("parent_comment_id") or "").strip()]

    comment_ids = {
        str(row.get("comment_id") or "").strip()
        for row in comment_rows
        if str(row.get("comment_id") or "").strip()
    }
    orphan_replies = [
        row for row in nested
        if str(row.get("parent_comment_id") or "").strip()
        and str(row.get("parent_comment_id") or "").strip() not in comment_ids
    ]
    parent_integrity_rate = (
        round((len(linked) - len(orphan_replies)) / len(nested), 4)
        if nested else 1.0
    )

    result = {
        "ok": bool(content_rows and comment_rows),
        "platform": "ks",
        "config": str(config_path),
        "data_root": str(root),
        "source_cycle": cycle.name,
        "structural_scope": "latest_raw_cycle_without_monitoring_start_filter",
        "input_files": [str(p) for p in files],
        "acceptance_output": str(output_path),
        "acceptance_summary": str(summary_path),
        "pipeline": {
            key: value for key, value in summary.items()
            if key not in {"input_files", "platform", "monitoring_start_time"}
        },
        "ppt_fields": {
            "videos_or_posts": len(content_rows),
            "source_type_counts": _source_type_counts(rows),
            "first_level_comments": len(first_level),
            "nested_replies": len(nested),
            "parent_linked_replies": len(linked),
            "orphan_parent_links": len(orphan_replies),
            "parent_integrity_rate": parent_integrity_rate,
            "content_public_ip_region_records": sum(
                1 for row in content_rows if str(row.get("ip_location") or "").strip()
            ),
            "comment_public_ip_region_records": sum(
                1 for row in comment_rows if str(row.get("ip_location") or "").strip()
            ),
            "content_regions": _region_counts(rows, comments=False),
            "comment_regions": _region_counts(rows, comments=True),
        },
        "classification": {
            "degraded": bool(summary.get("classification_degraded", False)),
            "degraded_records": int(summary.get("classification_degraded_records") or 0),
            "degraded_comment_records": int(summary.get("classification_degraded_comment_records") or 0),
            "errors": summary.get("classification_errors") or [],
            "note": (
                "If degraded=true, collection/normalization still succeeded. "
                "Attitude classification can be backfilled after the external model service recovers."
            ),
        },
    }

    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    summary_path.write_text(text, encoding="utf-8")
    latest_summary_path.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
