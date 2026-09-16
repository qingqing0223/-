from __future__ import annotations
from pathlib import Path
from pipeline.io_utils import read_jsonl, append_jsonl, read_json, write_json
from pipeline.normalizer import normalize_record
from pipeline.classifier import classify_records
from pipeline.language_detector import is_minority_language


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
    for needle, province in PROVINCE_ALIASES:
        if needle in text:
            return province
    # Keep a short public region label if the platform returns one we do not know;
    # never derive or store a raw IP address here.
    if len(text) <= 16 and not any(ch.isdigit() for ch in text):
        return text
    return ""


def _prepare_region_aliases(raw: dict) -> dict:
    """Copy a platform-provided public region/province label into ip_location.

    This does not geolocate users and does not accept raw IP addresses. It only
    reuses coarse public labels already returned by the platform/export.
    """
    if not isinstance(raw, dict):
        return raw
    out = dict(raw)
    candidates = [
        raw.get("ip_location"), raw.get("ip_region"), raw.get("ip_label"),
        raw.get("province"), raw.get("province_name"), raw.get("user_province"),
        raw.get("author_province"), raw.get("region"), raw.get("region_name"),
        raw.get("comment_ip_location"), raw.get("user_ip_location"),
    ]
    for parent_key in ("user", "author", "creator"):
        parent = raw.get(parent_key)
        if isinstance(parent, dict):
            candidates.extend([
                parent.get("ip_location"), parent.get("ip_region"), parent.get("ip_label"),
                parent.get("province"), parent.get("province_name"), parent.get("region"),
            ])
    for value in candidates:
        region = _canonical_public_region(value)
        if region:
            out["ip_location"] = region
            break
    return out


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
            raw = _prepare_region_aliases(raw)
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

    region_records = sum(1 for row in classified if str(row.get("ip_location") or "").strip())
    language_counts: dict[str, int] = {}
    minority_language_records = 0
    for row in classified:
        language = str(row.get("language") or "未知").strip() or "未知"
        language_counts[language] = language_counts.get(language, 0) + 1
        if is_minority_language(language):
            minority_language_records += 1

    total = len(classified)
    return {
        "platform": platform,
        "input_files": [str(p) for p in jsonl_files],
        "new_records": len(fresh),
        "classified_records": total,
        "region_records": region_records,
        "region_rate": round(region_records / total, 4) if total else 0.0,
        "minority_language_records": minority_language_records,
        "minority_language_rate": round(minority_language_records / total, 4) if total else 0.0,
        "language_counts": dict(sorted(language_counts.items(), key=lambda item: (-item[1], item[0]))),
        "total_seen": len(seen),
        # Private in-memory payload for the dashboard bridge. The orchestrator removes
        # this before writing status JSON, so a whole data batch is not duplicated there.
        "_classified_rows": classified,
    }
