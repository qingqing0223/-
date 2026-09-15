from __future__ import annotations
from opinion_monitor_v2 import OpinionMonitorV2


def classify_records(records: list[dict], concurrency: int = 4) -> list[dict]:
    if not records:
        return []

    monitor = OpinionMonitorV2(concurrency=concurrency)

    model_records = []
    for rec in records:
        model_rec = dict(rec)
        # The v2 model only consumes content/context. For video posts we feed the
        # combined publisher-side text evidence (caption/tags and later ASR/OCR).
        model_rec["content"] = rec.get("analysis_text") or rec.get("content") or ""
        model_rec["context"] = rec.get("context") or ""
        model_records.append(model_rec)

    results = monitor.classify_many(model_records, concurrency=concurrency)
    merged = []
    for rec, result in zip(records, results):
        row = dict(rec)
        decision = result.to_dict()
        row.update(decision)

        # Keep the collaborator's original status/type fields unchanged, while
        # explicitly naming what is being judged for downstream dashboards/reports.
        if row.get("record_type") == "video":
            row["video_attitude_status"] = decision.get("status")
            row["video_attitude_type"] = decision.get("type")
            row["video_attitude_scope"] = row.get("analysis_basis") or "caption"
            row["video_multimodal_complete"] = bool(row.get("asr_text") and row.get("ocr_text"))
        elif row.get("record_type") == "comment":
            row["audience_attitude_status"] = decision.get("status")
            row["audience_attitude_type"] = decision.get("type")
        else:
            row["post_attitude_status"] = decision.get("status")
            row["post_attitude_type"] = decision.get("type")

        merged.append(row)
    return merged
