"""Convert an explicit WeChat submission directory; never select an older batch."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .mp_export import FIELDS, FILES, atomic_json, build_tables
from .mp_poms import POMS_FIELDS, TABLE_NAMES, POMS_NOTE, poms_rows
from .mp_records import assess_record, merge_records, time_problem

ROOT = Path(__file__).resolve().parents[1]


def check_samples(directory: Path) -> None:
    for number, (name, fields) in enumerate(zip(TABLE_NAMES, POMS_FIELDS), 1):
        path = directory / f"{number:02d}_batch_{name}.json"
        rows = json.loads(path.read_text(encoding="utf-8-sig"))
        if not rows or not isinstance(rows, list) or any(not isinstance(row, dict) or list(row) != fields for row in rows):
            raise ValueError(f"table{number}: field order differs from supplied batch sample")


def validate_arrays(arrays: list[list[dict]]) -> None:
    if len(arrays) != 5:
        raise ValueError("Expected five POMS tables")
    for number, (rows, fields) in enumerate(zip(arrays, POMS_FIELDS), 1):
        if not isinstance(rows, list) or any(not isinstance(row, dict) or list(row) != fields for row in rows):
            raise ValueError(f"table{number}: expected ordered POMS English fields")
        for row in rows:
            if row.get("platform_name", row.get("platform")) != "微信公众号":
                raise ValueError(f"table{number}: non-WeChat platform in batch")
            for field, value in row.items():
                if field.endswith("_id") and value is not None and not isinstance(value, str):
                    raise ValueError(f"table{number}: IDs must be strings or null")
                if field.startswith("is_") and value is not None and type(value) is not bool:
                    raise ValueError(f"table{number}: {field} must be boolean or null")
                if field.endswith("_count") and value is not None and (type(value) is not int or value < 0):
                    raise ValueError(f"table{number}: {field} must be a nonnegative integer or null")
                if not field.startswith("is_") and not field.endswith("_count") and field != "matched_keywords" and value is not None and not isinstance(value, str):
                    raise ValueError(f"table{number}: {field} must be text or null")
            if number == 1:
                if not row["published_content_id"]:
                    raise ValueError("table1: missing content ID")
                if not isinstance(row["matched_keywords"], list) or not row["matched_keywords"] or any(not isinstance(v, str) for v in row["matched_keywords"]):
                    raise ValueError("table1: matched_keywords must be a nonempty string array")
                if row["is_valid_monitoring_data"] is not True and not row["invalid_reason"]:
                    raise ValueError("table1: invalid/pending review requires a reason")
    ids = [r["published_content_id"] for r in arrays[0]]
    if len(ids) != len(set(ids)):
        raise ValueError("table1: duplicate content IDs")
    for number in (1, 2, 3):
        if any(r["corresponding_published_content_id"] not in ids for r in arrays[number]):
            raise ValueError(f"table{number + 1}: content ID absent from table1")
    comments = {(r["corresponding_published_content_id"], r["comment_id"]) for r in arrays[1]}
    if any((r["corresponding_published_content_id"], r["comment_id"]) not in comments for r in arrays[3]):
        raise ValueError("table4: comment ID absent from table2")


def _read_csv(index: int, path: Path) -> list[list]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        if next(reader, None) != FIELDS[index]:
            raise ValueError(f"{path.name}: unexpected CSV header/order")
        output = []
        for number, values in enumerate(reader, 2):
            if len(values) != len(FIELDS[index]):
                raise ValueError(f"{path.name}: row {number} has wrong field count")
            converted = []
            for field, value in zip(POMS_FIELDS[index], values):
                if value == "":
                    converted.append(None)
                elif field.endswith("_count"):
                    if not value.isdecimal():
                        raise ValueError(f"{path.name}: row {number}, {field} is not an integer")
                    converted.append(int(value))
                else:
                    # Undo only this project's CSV formula-prefix escaping.
                    converted.append(value[1:] if len(value) > 1 and value[0] == "'" and value[1] in "=+-@\t\r" else value)
            output.append(converted)
        return output


def convert_batch(batch_dir: Path, *, source: str = "auto", config: dict | None = None,
                  samples_dir: Path = ROOT / "batch_test_samples") -> dict:
    batch_dir = batch_dir.resolve()
    if source not in ("auto", "csv", "jsonl"):
        raise ValueError("Unsupported source type")
    if not batch_dir.is_dir():
        raise ValueError("Batch directory does not exist")
    check_samples(samples_dir)
    metadata = batch_dir / "summary.json"
    cfg = json.loads(metadata.read_text(encoding="utf-8-sig")) if metadata.exists() else {}
    cfg.update(config or {})
    # The known daily batch has explicit scope even before its first export.
    if batch_dir.name == "2026-09-21_wechatmp02" and not cfg.get("monitoring_start_time"):
        cfg.update(json.loads((ROOT / "config/monitoring.wechat.2026-09-21.json").read_text(encoding="utf-8")))
    csvs = [batch_dir / name for name in FILES]
    jsonl = batch_dir / "search_contents.jsonl"
    if source == "auto":
        if any(p.exists() for p in csvs):
            source = "csv"  # Partial CSV sets are an error, never silently replaced.
        elif jsonl.exists():
            source = "jsonl"
        else:
            raise ValueError("No CSV/JSONL in this batch; collect data first. No older batch will be used.")
    if source in ("csv", "jsonl"):
        if not cfg.get("monitoring_start_time"):
            raise ValueError("Missing batch time scope: provide summary.json or --config")
        if source == "csv":
            if not all(p.exists() for p in csvs):
                raise ValueError("Incomplete CSV set: all five tables are required")
            arrays = [poms_rows(i, _read_csv(i, path)) for i, path in enumerate(csvs)]
        elif source == "jsonl":
            records = [json.loads(line) for line in jsonl.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
            if any(not isinstance(row, dict) for row in records):
                raise ValueError("Expected record objects in JSONL")
            records = [assess_record(r, cfg["monitoring_start_time"], cfg.get("keywords"), cfg.get("monitoring_end_time")) for r in merge_records([], records)]
            if any(not r["candidate_eligible"] for r in records):
                raise ValueError("JSONL contains out-of-scope rows; export the scoped candidate batch first")
            catalog_path = Path(cfg.get("wechat_mp_key_accounts", "config/key_accounts.wechat_mp.json"))
            if not catalog_path.is_absolute():
                catalog_path = ROOT / catalog_path
            catalog = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
            tables = build_tables(records, catalog, cfg.get("exported_at", ""))
            arrays = [poms_rows(i, rows) for i, rows in enumerate(tables)]
        else:
            raise ValueError("Unsupported source type")
        validate_arrays(arrays)
        for row in arrays[0]:
            problem = time_problem({"publish_time": row["published_at"], "collected_at": row["collected_at"]}, cfg["monitoring_start_time"], cfg.get("monitoring_end_time"))
            if problem:
                raise ValueError("table1 contains out-of-time or unreliable publication time")
            if cfg.get("keywords") and not set(row["matched_keywords"]).intersection(cfg["keywords"]):
                raise ValueError("table1 has no configured keyword hit")
    validate_arrays(arrays)
    # Validate every table before replacing any transport file. Source files stay intact.
    for number, rows in enumerate(arrays, 1):
        atomic_json(batch_dir / f"table{number}_batch.json", rows)
    report = {"source": source, "status": "CONVERTED",
              "table_counts": [len(rows) for rows in arrays], "sample_fields_checked": True,
              "monitoring_start_time": cfg.get("monitoring_start_time"), "monitoring_end_time": cfg.get("monitoring_end_time"),
              "note": POMS_NOTE, "network_requests": 0}
    atomic_json(batch_dir / "poms_conversion.json", report)
    return report
