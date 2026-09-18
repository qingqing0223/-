from __future__ import annotations

import json
import os
import re
import urllib.request

SOURCE_TYPES = [
    "权威媒体/新闻评论",
    "自媒体观点",
    "普通用户舆情",
    "律师/专家解读",
    "二创/剪辑解读",
]

OFFICIAL_MARKERS = (
    "人民日报", "新华社", "央视", "中央广播电视总台", "中国新闻网", "中国日报",
    "人民网", "新华网", "央广网", "光明日报", "法治日报", "中国青年报",
    "澎湃新闻", "界面新闻", "北京日报", "上海发布", "发布", "融媒体", "电视台",
    "广播电视台", "新闻中心", "政府", "公安", "法院", "检察院", "共青团",
)
EXPERT_MARKERS = (
    "律师", "律师事务所", "教授", "副教授", "专家", "研究员", "学者", "博士",
    "研究院", "研究中心", "评论员",
)
REMIX_MARKERS = (
    "二创", "混剪", "剪辑", "搬运", "转载", "盘点", "合集", "解说", "切片",
    "reaction", "重剪", "再创作",
)
SELF_MEDIA_MARKERS = (
    "说", "观察", "评论", "锐评", "观点", "漫谈", "聊", "看世界", "工作室",
    "自媒体", "博主", "UP主", "主播",
)


def _text(row: dict) -> str:
    return " ".join(
        str(row.get(k) or "")
        for k in ("author", "content", "context", "tag_text", "analysis_text")
    )


def heuristic_source_type(row: dict) -> str | None:
    text = _text(row)
    author = str(row.get("author") or "")

    if any(k.lower() in text.lower() for k in REMIX_MARKERS):
        return "二创/剪辑解读"
    if any(k in text for k in EXPERT_MARKERS):
        return "律师/专家解读"
    if any(k in author or k in text for k in OFFICIAL_MARKERS):
        return "权威媒体/新闻评论"
    if any(k in author or k in text for k in SELF_MEDIA_MARKERS):
        return "自媒体观点"
    return None


def _strip_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _llm_classify(unresolved: list[dict]) -> dict[str, str]:
    if not unresolved:
        return {}
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        return {}

    endpoint = os.environ.get(
        "DASHSCOPE_CHAT_COMPLETIONS_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    ).strip()
    model = os.environ.get("CONTENT_SOURCE_MODEL", "qwen3.8-flash").strip()
    try:
        timeout_seconds = int(os.environ.get("CONTENT_SOURCE_TIMEOUT_SECONDS", "25"))
    except Exception:
        timeout_seconds = 25
    timeout_seconds = max(5, min(timeout_seconds, 60))

    items = []
    for row in unresolved:
        items.append({
            "sample_id": str(row.get("sample_id") or ""),
            "platform": row.get("platform") or "",
            "record_type": row.get("record_type") or "",
            "author": row.get("author") or "",
            "text": (row.get("analysis_text") or row.get("content") or "")[:1800],
        })

    prompt = (
        "你是舆情内容来源类型分类器。请只依据给定账号名、正文/视频发布文案和平台信息，"
        "将每条记录严格归入以下五类之一：权威媒体/新闻评论、自媒体观点、普通用户舆情、"
        "律师/专家解读、二创/剪辑解读。不要判断政治立场，不要输出解释。"
        "返回严格JSON数组，每项格式为{\"sample_id\":\"...\",\"source_type\":\"五类之一\"}。\n"
        "判定规则：官方媒体、政务、法院检察院等机构账号归权威媒体/新闻评论；"
        "律师、教授、研究员、专家型账号归律师/专家解读；明显搬运、混剪、切片、二创归二创/剪辑解读；"
        "具有稳定栏目化观点输出的个人/机构账号归自媒体观点；普通个人随手发布归普通用户舆情。\n"
        "数据：" + json.dumps(items, ensure_ascii=False)
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "只输出合法JSON，不要Markdown。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            obj = json.loads(resp.read().decode("utf-8", errors="replace"))
        content = obj["choices"][0]["message"]["content"]
        data = json.loads(_strip_fence(content))
        out = {}
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                sid = str(item.get("sample_id") or "")
                typ = item.get("source_type")
                if sid and typ in SOURCE_TYPES:
                    out[sid] = typ
        return out
    except Exception:
        return {}


def classify_source_types(records: list[dict]) -> list[dict]:
    """Attach a non-blocking source/content type label to each record.

    Existing v2 attitude classification remains the source of truth for attitude.
    This auxiliary classifier is intentionally independent: failures fall back to
    heuristics/defaults and never block the realtime pipeline.
    """
    if not records:
        return []

    rows = [dict(r) for r in records]
    unresolved = []
    for row in rows:
        label = heuristic_source_type(row)
        if label:
            row["source_type"] = label
            row["source_type_method"] = "heuristic"
        else:
            unresolved.append(row)

    llm_labels = _llm_classify(unresolved)
    for row in unresolved:
        sid = str(row.get("sample_id") or "")
        label = llm_labels.get(sid)
        if label:
            row["source_type"] = label
            row["source_type_method"] = "llm_batch"
        else:
            row["source_type"] = "普通用户舆情"
            row["source_type_method"] = "fallback"

    for row in rows:
        typ = row.get("source_type") or "普通用户舆情"
        if row.get("record_type") == "video":
            row["video_content_type"] = {
                "权威媒体/新闻评论": "权威媒体/新闻评论",
                "自媒体观点": "自媒体观点视频",
                "普通用户舆情": "普通用户舆情视频",
                "律师/专家解读": "律师/专家解读",
                "二创/剪辑解读": "二创/剪辑解读",
            }.get(typ, typ)
    return rows
