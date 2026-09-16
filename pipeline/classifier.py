from __future__ import annotations

from opinion_monitor_v2 import OpinionMonitorV2

from .content_source_classifier import classify_source_types


def _safe_error_text(exc: Exception, limit: int = 600) -> str:
    text = f"{type(exc).__name__}: {exc}".replace("\r", " ").replace("\n", " ").strip()
    return text[:limit]


def _attach_attitude_fields(row: dict, decision: dict) -> None:
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


def _degraded_rows(records: list[dict], exc: Exception) -> list[dict]:
    """Preserve normalized records when the external attitude model is unavailable.

    Collection/normalization is the source of truth for whether a record exists.
    A classifier outage (missing quota, arrears, timeout, transient API failure, etc.)
    must never discard already collected posts/comments or their hierarchy/IP-region
    fields. Downstream reporting can explicitly see that attitude classification is
    unavailable and retry it later.
    """
    error = _safe_error_text(exc)
    rows = []
    for rec in records:
        row = dict(rec)
        decision = {"status": "unclassified", "type": None}
        row.update(decision)
        row["classification_ok"] = False
        row["classification_state"] = "degraded"
        row["classification_error"] = error
        row["classification_method"] = "fallback_preserve_record"
        _attach_attitude_fields(row, decision)
        rows.append(row)
    return rows


def classify_records(records: list[dict], concurrency: int = 4) -> list[dict]:
    if not records:
        return []

    model_records = []
    for rec in records:
        model_rec = dict(rec)
        # The v2 model only consumes content/context. For video posts we feed the
        # combined publisher-side text evidence (caption/tags and later ASR/OCR).
        model_rec["content"] = rec.get("analysis_text") or rec.get("content") or ""
        model_rec["context"] = rec.get("context") or ""
        model_records.append(model_rec)

    try:
        monitor = OpinionMonitorV2(concurrency=concurrency)
        results = monitor.classify_many(model_records, concurrency=concurrency)
        if len(results) != len(records):
            raise RuntimeError(
                f"classifier result length mismatch: input={len(records)} output={len(results)}"
            )

        merged = []
        for rec, result in zip(records, results):
            row = dict(rec)
            decision = result.to_dict()
            row.update(decision)
            row["classification_ok"] = True
            row["classification_state"] = "ok"
            row["classification_error"] = ""
            row["classification_method"] = "v2"
            _attach_attitude_fields(row, decision)
            merged.append(row)
    except Exception as exc:
        merged = _degraded_rows(records, exc)

    # Independent auxiliary classification for the five content-source categories
    # used in the reporting table. Its own LLM path is non-blocking and falls back
    # to heuristics/defaults, so source-type reporting can still proceed when the
    # attitude service is unavailable.
    return classify_source_types(merged)
