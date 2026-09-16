from __future__ import annotations

import re
from typing import Any

# Dashboard-facing language labels.  The detector intentionally prefers explicit
# platform/export metadata; script heuristics are only a fallback and carry a
# lower confidence value.
LANGUAGE_ALIASES = {
    "中文": "汉语", "汉语": "汉语", "普通话": "汉语", "zh": "汉语", "zh-cn": "汉语",
    "藏语": "藏语", "藏文": "藏语", "tibetan": "藏语", "bo": "藏语",
    "维吾尔语": "维吾尔语", "维语": "维吾尔语", "维文": "维吾尔语", "uyghur": "维吾尔语", "ug": "维吾尔语",
    "蒙古语": "蒙古语", "蒙语": "蒙古语", "蒙古文": "蒙古语", "蒙文": "蒙古语", "mongolian": "蒙古语", "mn": "蒙古语",
    "壮语": "壮语", "壮文": "壮语", "zhuang": "壮语", "za": "壮语",
    "哈萨克语": "哈萨克语", "哈萨克文": "哈萨克语", "kazakh": "哈萨克语", "kk": "哈萨克语",
    "彝语": "彝语", "彝文": "彝语", "yi": "彝语",
    "朝鲜语": "朝鲜语", "朝鲜文": "朝鲜语", "韩语": "朝鲜语", "korean": "朝鲜语", "ko": "朝鲜语",
    "英语": "英语", "英文": "英语", "english": "英语", "en": "英语",
}

MINORITY_LANGUAGE_LABELS = {
    "藏语", "维吾尔语", "蒙古语", "壮语", "哈萨克语", "彝语", "朝鲜语",
}

EXPLICIT_LANGUAGE_KEYS = (
    "language", "lang", "language_name", "content_language", "text_language",
    "comment_language", "detected_language",
)

# Modern standard Zhuang uses Latin script, so generic Latin detection cannot
# distinguish it from Chinese pinyin/English.  These markers are deliberately
# conservative and should be supplemented by a verified keyword pack.
ZHUANG_MARKERS = (
    "vahcuengh", "bouxcuengh", "cuengh", "gvanhjsih", "gvangjsih",
)

# Characters highly characteristic of modern Uyghur Arabic orthography. Arabic
# script alone is not enough because Kazakh and other languages can share it.
UYGHUR_MARKERS = set("ەېىۆۇۈڭئ")


def normalize_language_label(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    key = text.lower().replace("_", "-")
    if key in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[key]
    # Handle labels such as "维吾尔文/中文" by preferring the first explicit match.
    for alias, canonical in LANGUAGE_ALIASES.items():
        if len(alias) >= 2 and alias.lower() in key:
            return canonical
    return ""


def is_minority_language(label: Any) -> bool:
    return normalize_language_label(label) in MINORITY_LANGUAGE_LABELS or str(label or "").strip() in MINORITY_LANGUAGE_LABELS


def _count_range(text: str, start: int, end: int) -> int:
    return sum(1 for ch in text if start <= ord(ch) <= end)


def _explicit_language(raw: dict) -> str:
    for key in EXPLICIT_LANGUAGE_KEYS:
        label = normalize_language_label(raw.get(key))
        if label:
            return label
    # Some exports nest language metadata under author/user/content objects.
    for parent_key in ("author", "user", "creator", "content_meta", "meta"):
        parent = raw.get(parent_key)
        if not isinstance(parent, dict):
            continue
        for key in EXPLICIT_LANGUAGE_KEYS:
            label = normalize_language_label(parent.get(key))
            if label:
                return label
    return ""


def detect_language(raw: dict | None, text: Any) -> dict:
    """Return a conservative language label and provenance metadata.

    The function never calls an external service and never infers identity or
    ethnicity.  It only labels the language/script of public text content.
    """
    raw = raw if isinstance(raw, dict) else {}
    explicit = _explicit_language(raw)
    if explicit:
        return {
            "language": explicit,
            "language_method": "platform_metadata",
            "language_confidence": "high",
            "language_script": "",
        }

    s = str(text or "")
    if not s.strip():
        return {
            "language": "未知",
            "language_method": "empty",
            "language_confidence": "low",
            "language_script": "",
        }

    tibetan = _count_range(s, 0x0F00, 0x0FFF)
    mongolian = _count_range(s, 0x1800, 0x18AF) + _count_range(s, 0x11660, 0x1167F)
    yi = _count_range(s, 0xA000, 0xA48F)
    hangul = _count_range(s, 0xAC00, 0xD7AF) + _count_range(s, 0x1100, 0x11FF)
    arabic = _count_range(s, 0x0600, 0x06FF) + _count_range(s, 0x0750, 0x077F)
    cjk = _count_range(s, 0x4E00, 0x9FFF)

    if tibetan >= 2:
        return {"language": "藏语", "language_method": "unicode_script", "language_confidence": "high", "language_script": "Tibetan"}
    if mongolian >= 2:
        return {"language": "蒙古语", "language_method": "unicode_script", "language_confidence": "high", "language_script": "Mongolian"}
    if yi >= 2:
        return {"language": "彝语", "language_method": "unicode_script", "language_confidence": "high", "language_script": "Yi"}
    if hangul >= 2:
        return {"language": "朝鲜语", "language_method": "unicode_script", "language_confidence": "high", "language_script": "Hangul"}

    lowered = s.lower()
    if any(re.search(rf"(?<![a-z]){re.escape(marker)}(?![a-z])", lowered) for marker in ZHUANG_MARKERS):
        return {"language": "壮语", "language_method": "zhuang_marker", "language_confidence": "medium", "language_script": "Latin"}

    if arabic >= 2:
        marker_count = sum(1 for ch in s if ch in UYGHUR_MARKERS)
        if marker_count >= 2 or marker_count / max(arabic, 1) >= 0.08:
            return {"language": "维吾尔语", "language_method": "uyghur_script_marker", "language_confidence": "medium", "language_script": "Arabic"}
        # Do not force an Arabic-script text into Uyghur when the evidence is weak.
        return {"language": "阿拉伯字母语言", "language_method": "unicode_script", "language_confidence": "low", "language_script": "Arabic"}

    if cjk >= 2:
        return {"language": "汉语", "language_method": "unicode_script", "language_confidence": "high", "language_script": "Han"}

    latin = len(re.findall(r"[A-Za-z]", s))
    if latin >= 4:
        return {"language": "英语/拉丁字母待核实", "language_method": "unicode_script", "language_confidence": "low", "language_script": "Latin"}

    return {"language": "未知", "language_method": "heuristic_unknown", "language_confidence": "low", "language_script": ""}
