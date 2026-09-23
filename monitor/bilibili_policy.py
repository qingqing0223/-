from __future__ import annotations

"""Bilibili-specific scope helpers for the 2026 promotion-week monitor.

The search layer may use broader discovery terms, but formal collection only
admits content whose own public text supports relevance to this monitoring
event.  Time-window enforcement remains centralized in monitor.ingest so this
module never silently changes the configured monitoring_start_time.
"""

_TEXT_FIELDS = (
    "title",
    "desc",
    "description",
    "body",
    "content",
    "context",
    "tags",
    "tag_text",
    "asr_text",
    "ocr_text",
)

_EXACT_OR_STRONG = (
    "2026年民族团结进步宣传周",
    "首个民族团结进步宣传周",
    "民族团结进步宣传周",
    "促进民族团结进步，奋进伟大复兴征程",
    "促进民族团结进步,奋进伟大复兴征程",
    "民族团结进步倡议",
    "民族团结进步宣传周主场活动",
)

_EXCLUDED_WEEKS = (
    "网络安全宣传周",
    "国家网络安全宣传周",
    "推广普通话宣传周",
    "节能宣传周",
    "宪法宣传周",
    "绿色出行宣传周",
)


def _compact(value) -> str:
    return (
        "".join(str(value or "").split())
        .replace("，", ",")
        .replace("：", ":")
        .replace("—", "-")
        .replace("－", "-")
    )


def bilibili_campaign_text(row: dict) -> str:
    return _compact(" ".join(str(row.get(key) or "") for key in _TEXT_FIELDS))


def is_bilibili_campaign_relevant(row: dict) -> bool:
    """Return True only when the content itself supports campaign relevance.

    Search keyword provenance alone is intentionally not sufficient because a
    broad Bilibili search can return unrelated videos.  The formal six search
    keywords stay in config/preflight; this helper only performs the admission
    gate on returned content.
    """
    if not isinstance(row, dict):
        return False

    text = bilibili_campaign_text(row)
    if not text:
        return False

    if any(_compact(phrase) in text for phrase in _EXCLUDED_WEEKS):
        # A result mentioning another publicity week is admitted only when it
        # also explicitly contains the target campaign wording.
        if "民族团结进步宣传周" not in text:
            return False

    if any(_compact(phrase) in text for phrase in _EXACT_OR_STRONG):
        return True

    # The artistic slogan is specific only when both halves are present.
    if "石榴花开" in text and "铸牢中华民族共同体意识" in text:
        return True

    return False
