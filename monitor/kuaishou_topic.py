from __future__ import annotations

from dataclasses import asdict, dataclass


# These terms are discovery inputs supplied by the data-integration lead.  They
# are deliberately not treated as an allow-list for final inclusion.
KUAISHOU_REFERENCE_SEARCH_TERMS = (
    "2026年民族团结进步宣传周",
    "首个民族团结进步宣传周",
    "促进民族团结进步，奋进伟大复兴征程",
    "民族团结进步倡议",
    "民族团结进步宣传周主场活动",
    "石榴花开——铸牢中华民族共同体意识",
)

RELEVANT_WEEK_PHRASE = "民族团结进步宣传周"
WEEK_NAME_VARIANTS = (RELEVANT_WEEK_PHRASE, "民族团结宣传周", "团结进步宣传周")
WEEK_EVENT_SIGNALS = (
    "启动", "启动仪式", "主场活动", "展演", "宣传活动", "主题活动", "举办", "开展", "开幕", "将于",
    "倡议", "倡议书", "主题宣传片",
)
DIRECT_CORE_SIGNALS = (
    "民族团结进步倡议", "民族团结进步倡议书", "民族团结进步宣传周主场活动",
    "民族团结进步宣传周主题宣传片", "2026年民族团结进步宣传周主场活动",
)
OFFICIAL_THEME = "促进民族团结进步，奋进伟大复兴征程"
HISTORICAL_YEAR_SIGNALS = ("2025年", "2024年", "2023年", "2022年", "2021年", "2020年")

REVIEW_ONLY_SIGNALS = (
    ("民族团结进步宣传月", "宣传月内容不能仅因搜索命中自动纳入"),
    ("民族团结进步活动月", "活动月内容不能仅因搜索命中自动纳入"),
    ("民族团结进步促进法", "促进法科普不能仅因搜索命中自动纳入"),
)


@dataclass(frozen=True)
class KuaishouTopicDecision:
    status: str
    reason: str
    matched_evidence: tuple[str, ...]

    def as_dict(self) -> dict:
        value = asdict(self)
        value["matched_evidence"] = list(self.matched_evidence)
        return value


def _topic_text(record: dict) -> str:
    return "\n".join(str(record.get(key) or "") for key in (
        "analysis_text", "content", "context", "tag_text", "asr_text", "ocr_text"
    ))


def assess_kuaishou_topic(record: dict) -> KuaishouTopicDecision:
    """Assess a time-scoped search/homepage hit without using search terms as a whitelist.

    An explicit occurrence of ``民族团结进步宣传周`` is strong enough for automatic
    inclusion, including a city/county prefix.  Other keyword hits remain in the
    candidate pool for human review; generic campaign-month, ordinary activity,
    and law-explainer content is not auto-promoted.
    """
    text = _topic_text(record)
    historical = tuple(year for year in HISTORICAL_YEAR_SIGNALS if year in text and "2026年" not in text)
    if historical:
        return KuaishouTopicDecision(
            "candidate_review",
            "出现历史年份语境，不能仅因宣传周词汇自动纳入本届监测",
            historical,
        )

    direct = tuple(signal for signal in DIRECT_CORE_SIGNALS if signal in text)
    if direct:
        return KuaishouTopicDecision("relevant", "正文直接对应本届宣传周核心事项", direct)

    if OFFICIAL_THEME in text and any(signal in text for signal in ("宣传周", "2026", "活动", "启动", "主场")):
        return KuaishouTopicDecision(
            "relevant", "正文将本届官方主题与宣传周/活动直接关联", (OFFICIAL_THEME,)
        )

    matched_week_name = next((phrase for phrase in WEEK_NAME_VARIANTS if phrase in text), "")
    if matched_week_name:
        event_evidence = tuple(signal for signal in WEEK_EVENT_SIGNALS if signal in text)
        if event_evidence:
            return KuaishouTopicDecision(
                "relevant",
                "正文明确描述民族团结进步宣传周活动（含地方宣传周及常见简称）",
                (matched_week_name, *event_evidence),
            )
        return KuaishouTopicDecision(
            "candidate_review",
            "明确出现“民族团结进步宣传周”，已列为优先相关候选；仅标签/弱上下文不足以自动纳入",
            (matched_week_name,),
        )

    review_reasons = [reason for signal, reason in REVIEW_ONLY_SIGNALS if signal in text]
    if review_reasons:
        return KuaishouTopicDecision(
            "candidate_review",
            "；".join(dict.fromkeys(review_reasons)),
            tuple(signal for signal, _ in REVIEW_ONLY_SIGNALS if signal in text),
        )

    source_keywords = list(record.get("source_keywords") or [])
    if record.get("source_keyword"):
        source_keywords.append(str(record["source_keyword"]))
    source_keywords = list(dict.fromkeys(x.strip() for x in source_keywords if str(x).strip()))
    source_file = str(record.get("source_file") or "").lower()
    if "creator" in source_file:
        return KuaishouTopicDecision(
            "candidate_review",
            "重点/相关账号主页作品：已进入候选池，但正文证据不足，需人工复核",
            tuple(source_keywords),
        )
    if source_keywords:
        return KuaishouTopicDecision(
            "candidate_review",
            "关键词搜索命中：已进入候选池，但搜索词不是最终有效数据白名单",
            tuple(source_keywords),
        )
    return KuaishouTopicDecision(
        "candidate_review",
        "候选来源存在，但缺少可自动确认主题相关性的正文证据",
        (),
    )


def candidate_source(record: dict) -> str:
    explicit = str(record.get("_candidate_source_hint") or "").strip()
    if explicit:
        return explicit
    source_file = str(record.get("source_file") or "").lower()
    if "creator" in source_file:
        return "account_homepage"
    if "search" in source_file:
        return "keyword_search"
    if "detail" in source_file:
        return "detail_recovery"
    return "unknown"
