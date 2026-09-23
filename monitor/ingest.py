from __future__ import annotations
from datetime import datetime
import json
import re
from pathlib import Path
from pipeline.io_utils import read_jsonl, append_jsonl, read_json, write_json
from pipeline.normalizer import normalize_record
from pipeline.classifier import classify_records
from pipeline.language_detector import is_minority_language

# ----小红书业务过滤配置（仅xhs平台生效）----
MONITOR_START_TS_MS = 1789430400000  # 2026‑09‑16 00:00 北京时间 毫秒
FILTER_KEYWORDS = [
    "2026年民族团结进步宣传周",
    "首个民族团结进步宣传周",
    "促进民族团结进步，奋进伟大复兴征程",
    "民族团结进步倡议",
    "民族团结进步宣传周主场活动",
    "石榴花开——铸牢中华民族共同体意识"
]


COUNTRY_ONLY_REGION_LABELS = {"中国", "中国大陆", "中华人民共和国", "China", "Mainland China", "PRC", "CN"}

PROVINCE_ALIASES = [
    ("内蒙古", "内蒙古"), ("广西", "广西"), ("西藏", "西藏"), ("宁夏", "宁夏"), ("新疆", "新疆"),
    ("香港", "香港"), ("澳门", "澳门"),
    ("北京", "北京"), ("天津", "天津"), ("上海", "上海"), ("重庆", "重庆"),
    ("河北", "河北"), ("山西", "山西"), ("辽宁", "辽宁"), ("吉林", "吉林"), ("黑龙江", "黑龙江"),
    ("江苏", "江苏"), ("浙江", "浙江"), ("安徽", "安徽"), ("福建", "福建"), ("江西", "江西"),
    ("山东", "山东"), ("河南", "河南"), ("湖北", "湖北"), ("湖南", "湖南"), ("广东", "广东"),
    ("海南", "海南"), ("四川", "四川"), ("贵州", "贵州"), ("云南", "云南"), ("陕西", "陕西"),
    ("甘肃", "甘肃"), ("青海", "青海"), ("台湾", "台湾"),
]


def _canonical_public_region(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    for prefix in ("IP属地：", "IP属地:", "IP属地", "来自：", "来自:", "来自"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    if text in COUNTRY_ONLY_REGION_LABELS or re.fullmatch(r"[A-Za-z]{2,3}", text):
        return ""
    for needle, province in PROVINCE_ALIASES:
        if needle in text:
            return province
    if len(text) <= 16 and not any(ch.isdigit() for ch in text):
        return text
    return ""


def _prepare_region_aliases(raw: dict) -> dict:
    if not isinstance(raw, dict):
        return raw
    out = dict(raw)
    candidates = [
        raw.get("ip_location"), raw.get("ip_region"), raw.get("ip_label"),
        raw.get("province"), raw.get("province_name"), raw.get("user_province"),
        raw.get("author_province"), raw.get("region"), raw.get("region_name"),
        raw.get("comment_ip_location"), raw.get("user_ip_location"),
    ]
    for parent_key in ("user", "user_info", "author", "creator", "member"):
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


def _parse_iso_datetime(value, default_tz=None):
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        return None
    if dt.tzinfo is None and default_tz is not None:
        dt = dt.replace(tzinfo=default_tz)
    return dt


def _before_monitoring_start(rec: dict, monitoring_start_time: str) -> bool:
    start = _parse_iso_datetime(monitoring_start_time)
    if start is None:
        return False
    published = _parse_iso_datetime(rec.get("publish_time"), default_tz=start.tzinfo)
    if published is None:
        return False
    return published < start


def load_seen(path: Path) -> set[str]:
    data = read_json(path, {"seen": []})
    return set(map(str, data.get("seen", [])))


def save_seen(path: Path, seen: set[str]) -> None:
    write_json(path, {"seen": sorted(seen)})


def _merge_regions_into_existing(output_jsonl: Path, region_by_key: dict[str, str]) -> int:
    if not region_by_key or not output_jsonl.exists():
        return 0
    rows = list(read_jsonl(output_jsonl))
    updated = 0
    for row in rows:
        key = str(row.get("dedupe_key") or "").strip()
        region = region_by_key.get(key, "")
        if not key or not region:
            continue
        old = str(row.get("ip_location") or "").strip()
        if old:
            continue
        row["ip_location"] = region
        updated += 1
    if not updated:
        return 0

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_jsonl.with_suffix(output_jsonl.suffix + ".region.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(output_jsonl)
    return updated


def ingest_and_classify(platform: str, jsonl_files: list[Path], state_path: Path,
                        output_jsonl: Path, concurrency: int = 4,
                        monitoring_start_time: str = "", classify: bool = True) -> dict:
    seen = load_seen(state_path)
    fresh = []
    filtered_before_start = 0
    filtered_before_start_comment_records = 0
    filtered_before_start_content_records = 0
    region_by_key: dict[str, str] = {}

    raw_rows = 0
    raw_comment_rows = 0
    normalized_records = 0
    normalized_comment_records = 0
    normalization_dropped = 0
    duplicate_skipped = 0
    duplicate_comment_skipped = 0
    duplicate_content_skipped = 0

    for path in jsonl_files:
        is_comment_file = "comment" in path.name.lower()
        for raw in read_jsonl(path):
            raw_rows += 1
            if is_comment_file:
                raw_comment_rows += 1
            raw = _prepare_region_aliases(raw)

            # --------小红书笔记过滤：仅xhs、非评论文件生效 --------
            if platform == "xhs" and not is_comment_file:
                note_ts = raw.get("time", 0)            
                if note_ts < MONITOR_START_TS_MS:
                    continue

                title = raw.get("title", "") or ""
                desc = raw.get("desc", "") or ""
                full_text = title + desc
                hit = any(k in full_text for k in FILTER_KEYWORDS)
                if not hit:
                    continue
        # ---------------------------------------------------

            rec = normalize_record(raw, source_file=path.name, platform_hint=platform)
            if not rec:
                normalization_dropped += 1
                continue
            normalized_records += 1
            if rec.get("record_type") == "comment":
                normalized_comment_records += 1
            key = rec["dedupe_key"]
            region = _canonical_public_region(rec.get("ip_location"))
            if region:
                region_by_key[key] = region
            if key in seen:
                duplicate_skipped += 1
                if rec.get("record_type") == "comment":
                    duplicate_comment_skipped += 1
                else:
                    duplicate_content_skipped += 1
                continue
            seen.add(key)
            if _before_monitoring_start(rec, monitoring_start_time):
                filtered_before_start += 1
                if rec.get("record_type") == "comment":
                    filtered_before_start_comment_records += 1
                else:
                    filtered_before_start_content_records += 1
                continue
            if region:
                rec["ip_location"] = region
            fresh.append(rec)

    region_backfilled_records = _merge_regions_into_existing(output_jsonl, region_by_key)

    classification_enabled = bool(classify)
    classified = classify_records(fresh, concurrency=concurrency) if classification_enabled else fresh
    append_jsonl(output_jsonl, classified)
    save_seen(state_path, seen)

    region_records = sum(1 for row in classified if str(row.get("ip_location") or "").strip())
    language_counts: dict[str, int] = {}
    minority_language_records = 0
    for row in classified:
        language = str(row.get("language") or "未知").strip() or "未知"
        language_counts[language] = language_counts.get(language, 0) + 1
        if is_minority_language(language):
            minority_language_records += 1

    total = len(classified)
    classified_comment_records = sum(1 for row in classified if row.get("record_type") == "comment")
    classification_degraded_records = sum(1 for row in classified if row.get("classification_ok") is False)
    classification_degraded_comment_records = sum(
        1 for row in classified
        if row.get("record_type") == "comment" and row.get("classification_ok") is False
    )
    classification_errors = sorted({
        str(row.get("classification_error") or "").strip()
        for row in classified
        if row.get("classification_ok") is False and str(row.get("classification_error") or "").strip()
    })

    return {
        "platform": platform,
        "monitoring_start_time": monitoring_start_time,
        "input_files": [str(p) for p in jsonl_files],
        "raw_rows": raw_rows,
        "raw_comment_rows": raw_comment_rows,
        "normalized_records": normalized_records,
        "normalized_comment_records": normalized_comment_records,
        "normalization_dropped": normalization_dropped,
        "duplicate_skipped": duplicate_skipped,
        "new_records": len(fresh),
        "filtered_before_start": filtered_before_start,
        "filtered_before_start_comment_records": filtered_before_start_comment_records,
        "filtered_before_start_content_records": filtered_before_start_content_records,
        "duplicate_comment_skipped": duplicate_comment_skipped,
        "duplicate_content_skipped": duplicate_content_skipped,
        "classified_records": total,
        "classified_comment_records": classified_comment_records,
        "classification_degraded_records": classification_degraded_records,
        "classification_degraded_comment_records": classification_degraded_comment_records,
        "classification_enabled": classification_enabled,
        "classification_degraded": classification_degraded_records > 0,
        "classification_errors": classification_errors[:3],
        "region_records": region_records,
        "region_rate": round(region_records / total, 4) if total else 0.0,
        "region_backfilled_records": region_backfilled_records,
        "minority_language_records": minority_language_records,
        "minority_language_rate": round(minority_language_records / total, 4) if total else 0.0,
        "language_counts": dict(sorted(language_counts.items(), key=lambda item: (-item[1], item[0]))),
        "total_seen": len(seen),
        "_classified_rows": classified if classification_enabled else [],
    }
