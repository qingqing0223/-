from __future__ import annotations

import re

_PROVINCES = (
    "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门",
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林",
    "黑龙江", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
    "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西",
    "甘肃", "青海", "台湾",
)
_IP_LIKE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$|^[0-9a-fA-F:]{6,}$")
_COUNTRY_CODE_ONLY = re.compile(r"^[A-Za-z]{2,3}$")
_COUNTRY_ONLY = {"中国", "中国大陆", "中华人民共和国", "China", "Mainland China", "PRC", "CN"}


def coarse_public_region(value) -> str:
    """Return only a coarse public region label; never return a real IP address."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    for prefix in ("IP属地：", "IP属地:", "IP属地", "来自：", "来自:", "来自", "发布于：", "发布于:", "发布于", "所在地：", "所在地:", "所在地"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    if not text or _IP_LIKE.fullmatch(text):
        return ""
    if text in {"未知", "暂无", "无", "None", "null", "-", "--"}:
        return ""
    if _COUNTRY_CODE_ONLY.fullmatch(text) or text in _COUNTRY_ONLY:
        return ""
    for province in _PROVINCES:
        if province in text:
            return province
    if len(text) <= 16 and not any(ch.isdigit() for ch in text):
        return text
    return ""


def first_coarse_public_region(*values) -> str:
    """Return the first usable coarse public-region label from candidate fields."""
    for value in values:
        region = coarse_public_region(value)
        if region:
            return region
    return ""


_REGION_PROBE_KEYS = {
    "ip_label", "ip_location", "ip_region", "ipregion",
    "region", "region_name", "province", "province_name",
}


def _safe_probe_value(value) -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    text = str(value).strip()
    if not text or _IP_LIKE.fullmatch(text):
        return ""
    if len(text) > 24 or any(ch.isdigit() for ch in text):
        return ""
    return text


def public_region_probe(obj, *, max_depth: int = 4, max_items: int = 30) -> dict[str, str]:
    """Collect only short, non-IP public region-like source fields for local diagnostics."""
    found: dict[str, str] = {}

    def walk(value, path: str, depth: int) -> None:
        if depth > max_depth or len(found) >= max_items:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key)
                next_path = f"{path}.{key_text}" if path else key_text
                if key_text.lower() in _REGION_PROBE_KEYS:
                    probe = _safe_probe_value(child)
                    if probe:
                        found[next_path] = probe
                if isinstance(child, (dict, list)):
                    walk(child, next_path, depth + 1)
        elif isinstance(value, list):
            for index, child in enumerate(value[:10]):
                if isinstance(child, (dict, list)):
                    walk(child, f"{path}[{index}]", depth + 1)

    walk(obj, "", 0)
    return found
