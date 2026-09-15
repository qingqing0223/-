from __future__ import annotations
from opinion_monitor_v2 import OpinionMonitorV2

def classify_records(records: list[dict], concurrency: int = 4) -> list[dict]:
    if not records:
        return []
    monitor = OpinionMonitorV2(concurrency=concurrency)
    results = monitor.classify_many(records, concurrency=concurrency)
    merged = []
    for rec, result in zip(records, results):
        row = dict(rec)
        row.update(result.to_dict())
        merged.append(row)
    return merged
