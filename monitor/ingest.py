from __future__ import annotations
from pathlib import Path
from pipeline.io_utils import read_jsonl, append_jsonl, read_json, write_json
from pipeline.normalizer import normalize_record
from pipeline.classifier import classify_records

def load_seen(path: Path) -> set[str]:
    data = read_json(path, {"seen": []})
    return set(map(str, data.get("seen", [])))

def save_seen(path: Path, seen: set[str]) -> None:
    write_json(path, {"seen": sorted(seen)})

def ingest_and_classify(platform: str, jsonl_files: list[Path], state_path: Path,
                        output_jsonl: Path, concurrency: int = 4) -> dict:
    seen = load_seen(state_path)
    fresh = []

    for path in jsonl_files:
        for raw in read_jsonl(path):
            rec = normalize_record(raw, source_file=path.name, platform_hint=platform)
            if not rec:
                continue
            key = rec["dedupe_key"]
            if key in seen:
                continue
            seen.add(key)
            fresh.append(rec)

    classified = classify_records(fresh, concurrency=concurrency)
    append_jsonl(output_jsonl, classified)
    save_seen(state_path, seen)
    return {
        "platform": platform,
        "input_files": [str(p) for p in jsonl_files],
        "new_records": len(fresh),
        "classified_records": len(classified),
        "total_seen": len(seen),
        # Private in-memory payload for the dashboard bridge. The orchestrator removes
        # this before writing status JSON, so a whole data batch is not duplicated there.
        "_classified_rows": classified,
    }
