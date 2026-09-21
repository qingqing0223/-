"""Public WeChat article identity and scope rules; never calls a classifier."""
from __future__ import annotations

from datetime import datetime, timedelta
import html
import re
import unicodedata
from urllib.parse import parse_qs, urlencode, urlsplit

from .common import CN_TZ, clean_text, now_cn, stable_id

START = "2026-09-16T00:00:00+08:00"
EVENT = "民族团结进步宣传周"


def normalize_name(value: str) -> str:
    # Exact after Unicode/whitespace normalization. No substring or suffix guessing.
    return re.sub(r"[\s\u200b\ufeff]+", "", unicodedata.normalize("NFKC", value or "")).casefold()


def parse_display_time(text: str, reference: datetime | None = None) -> str:
    """Accept only a dedicated public timestamp, never surrounding article text."""
    s = clean_text(text)
    ref = (reference or now_cn()).astimezone(CN_TZ)
    m = re.fullmatch(r"(\d+)\s*(分钟|小时|天)前", s)
    if m:
        unit = {"分钟": "minutes", "小时": "hours", "天": "days"}[m[2]]
        return (ref - timedelta(**{unit: int(m[1])})).isoformat(timespec="seconds")
    m = re.fullmatch(r"(今天|昨天)(?:\s+(\d{1,2}):(\d{2}))?", s)
    if m:
        try:
            return (ref - timedelta(days=m[1] == "昨天")).replace(
                hour=int(m[2] or 0), minute=int(m[3] or 0), second=0, microsecond=0
            ).isoformat()
        except ValueError:
            return ""
    m = re.fullmatch(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?", s)
    if m:
        try:
            return datetime(*(int(x or 0) for x in m.groups()), tzinfo=CN_TZ).isoformat()
        except ValueError:
            return ""
    # A yearless month/day is intentionally ambiguous and left unknown.
    return ""


def canonical_article_url(url: str) -> str:
    try:
        p = urlsplit(html.unescape(url or ""))
        if p.scheme not in ("http", "https") or p.hostname != "mp.weixin.qq.com":
            return ""
        if re.fullmatch(r"/s/[A-Za-z0-9_-]+", p.path):
            return "https://mp.weixin.qq.com" + p.path
        q = parse_qs(p.query)
        if p.path.rstrip("/") == "/s" and all(q.get(k) for k in ("__biz", "mid", "idx")):
            return "https://mp.weixin.qq.com/s?" + urlencode({k: q[k][0] for k in ("__biz", "mid", "idx")})
    except ValueError:
        pass
    return ""


def assign_identity(row: dict) -> dict:
    row = dict(row)
    canonical = canonical_article_url(row.get("canonical_url") or row.get("url", ""))
    title = normalize_name(row.get("title", ""))
    author = normalize_name(row.get("author", ""))
    # Relative timestamps change between searches. Title + account is the stable
    # fallback; an exact displayed calendar date can disambiguate republications.
    exact_date = row.get("publish_date_exact", "")
    basis = canonical or "metadata:" + "|".join((title, author, exact_date))
    row["canonical_url"] = canonical
    row["identity_method"] = "canonical_url" if canonical else "normalized_title_account"
    row["content_id"] = "wxmp_" + stable_id(basis)
    row["dedupe_key"] = row["content_id"]
    row["identity_title_account"] = stable_id(title, author) if title and author else ""
    row["matched_keywords"] = sorted(set(row.get("matched_keywords", []) + ([row["source_keyword"]] if row.get("source_keyword") else [])))
    return row


def merge_records(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """Merge across keywords/runs, retain the first ID and all observed keywords.

    A metadata fallback may bridge to a subsequently discovered canonical URL.
    Distinct known canonical URLs or exact publication dates never get merged.
    """
    merged: list[dict] = []
    by_id: dict[str, dict] = {}
    by_metadata: dict[str, list[dict]] = {}
    for original in [*existing, *incoming]:
        row = assign_identity(original)
        candidate = by_id.get(row["content_id"])
        meta = row["identity_title_account"]
        if candidate is None and meta:
            compatible = []
            for old in by_metadata.get(meta, []):
                if old.get("canonical_url") and row.get("canonical_url") and old["canonical_url"] != row["canonical_url"]:
                    continue
                if old.get("publish_date_exact") and row.get("publish_date_exact") and old["publish_date_exact"] != row["publish_date_exact"]:
                    continue
                compatible.append(old)
            if len(compatible) == 1:
                candidate = compatible[0]
        if candidate is None:
            computed_id = row["content_id"]
            # Preserve persisted identity even when a later canonical URL exists.
            if original.get("identity_method") and original.get("content_id"):
                row["content_id"] = original["content_id"]
                row["dedupe_key"] = row["content_id"]
                row["identity_method"] = original["identity_method"]
            merged.append(row)
            by_id[row["content_id"]] = row
            by_id[computed_id] = row
            if meta:
                by_metadata.setdefault(meta, []).append(row)
            continue
        candidate["matched_keywords"] = sorted(set(candidate["matched_keywords"] + row["matched_keywords"]))
        candidate["last_seen_at"] = max(candidate.get("last_seen_at", candidate.get("collected_at", "")), row.get("collected_at", ""))
        if row.get("publish_time_source") == "sogou_public_footer_epoch" and candidate.get("publish_time_source") != "sogou_public_footer_epoch":
            candidate["publish_time"] = row["publish_time"]
            candidate["publish_time_source"] = row["publish_time_source"]
        for field in ("canonical_url", "author", "publish_time", "publish_date_exact", "publish_time_source"):
            if not candidate.get(field) and row.get(field):
                candidate[field] = row[field]
        for field in ("views", "likes", "comments", "reposts", "shares", "favorites"):
            if row.get(field) is not None:
                candidate[field] = row[field]
        if len(row.get("content", "")) > len(candidate.get("content", "")):
            candidate["content"] = row["content"]
        by_id[row["content_id"]] = candidate
    return merged


def time_problem(row: dict, start: str = START, end: str | None = None) -> str:
    try:
        published = datetime.fromisoformat(row.get("publish_time") or "")
        if published.tzinfo is None:
            return "发布时间缺少时区，待人工核验"
    except (ValueError, TypeError):
        return "无可靠公开发布时间，待人工核验"
    if published < datetime.fromisoformat(start):
        return "发布时间早于正式监测开始时间"
    if end and published > datetime.fromisoformat(end):
        return "发布时间晚于本批次监测结束时间"
    try:
        collected = datetime.fromisoformat(row.get("collected_at") or now_cn().isoformat())
        if collected.tzinfo is None:
            return "采集时间缺少时区，待人工核验"
    except (ValueError, TypeError):
        return "采集时间格式错误，待人工核验"
    if published > collected:
        return "发布时间晚于采集时间，待人工核验"
    return ""


def validate_record(row: dict, start: str = START, end: str | None = None) -> tuple[bool, str]:
    problem = time_problem(row, start, end)
    if problem:
        return False, problem
    published = datetime.fromisoformat(row["publish_time"])
    text = normalize_name(row.get("title", "") + " " + row.get("content", ""))
    if re.search(r"有偿代写|代发软文|推广代发|低价刷量|商业广告", text):
        return False, "商业广告或有偿推广结果"
    # Keyword that triggered a search is not evidence of relevance.
    if re.search(r"20(?!26)\d{2}年?(?:首个)?" + EVENT, text) and not re.search(r"2026年?(?:首个)?" + EVENT, text):
        return False, "其他年份的民族团结进步宣传周"
    if re.search(r"2026年?" + EVENT, text):
        return True, ""
    if "首个" + EVENT in text and published.year == 2026:
        return True, ""
    # Alternate official phrases need event AND explicit current-year context.
    phrases = ("促进民族团结进步，奋进伟大复兴征程", "民族团结进步倡议", EVENT + "主场活动", "石榴花开")
    if "2026" in text and EVENT in text and any(normalize_name(p) in text for p in phrases):
        return True, ""
    return False, "缺少本次2026年民族团结进步宣传周的明确上下文，待人工核验"


def assess_record(row: dict, start: str = START, keywords: list[str] | None = None, end: str | None = None) -> dict:
    """Separate table eligibility (time + real search hit) from topic review."""
    result = dict(row)
    temporal = time_problem(row, start, end)
    matched = set(row.get("matched_keywords") or [])
    if row.get("source_keyword"):
        matched.add(row["source_keyword"])
    searched = bool(matched if keywords is None else matched.intersection(keywords))
    valid, reason = validate_record(row, start, end)
    certain_invalid = reason in ("商业广告或有偿推广结果", "其他年份的民族团结进步宣传周")
    status = "是" if valid else "否" if certain_invalid else "待核验"
    if not searched:
        reason, status, valid = "无正式关键词实际搜索命中记录", "待核验", False
    result.update(time_eligible=not temporal, candidate_eligible=not temporal and searched,
                  review_status=status, is_valid=valid and not temporal and searched,
                  invalid_reason=reason, time_exclusion_reason=temporal)
    return result


def candidate_counts(rows: list[dict]) -> dict:
    candidates = [r for r in rows if r.get("candidate_eligible")]
    return {"total_candidates": len(candidates),
            "valid_articles": sum(r["review_status"] == "是" for r in candidates),
            "invalid_articles": sum(r["review_status"] == "否" for r in candidates),
            "pending_review_articles": sum(r["review_status"] == "待核验" for r in candidates)}


def key_account(name: str, catalog: dict) -> tuple[bool, str]:
    normalized = normalize_name(name)
    if normalized:
        for category in catalog.get("categories", []):
            if normalized in {normalize_name(n) for n in category["accounts"]}:
                return True, category["account_type"]
    return False, ""
