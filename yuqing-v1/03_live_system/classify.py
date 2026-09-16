# -*- coding: utf-8 -*-
"""民族相关舆情相关性判断（可后续替换为模型/规则升级版）"""

RELEVANT_KEYWORDS = [
    "民族团结", "进步促进法", "促进法", "民族工作", "民族地区", "少数民族",
    "民族政策", "民族事务", "民族宗教", "民族平等", "民族团结进步",
    "新疆", "西藏", "青海", "甘肃", "四川", "内蒙古", "云南", "宁夏", "广西",
    "维吾尔", "哈萨克", "藏族", "彝", "回族", "苗族", "侗", "瑶", "壮",
    "满族", "民族", "反民族歧视", "就业歧视",
]


def classify(text, platform="", title=""):
    """返回 (是否相关, 说明)。命中关键词即视为相关，未命中进入待复核。"""
    hay = f"{title or ''} {text or ''} {platform or ''}"
    if not hay.strip():
        return False, "无正文，无法判断"
    hits = [k for k in RELEVANT_KEYWORDS if k in hay]
    if hits:
        return True, "命中关键词：" + "、".join(hits[:6])
    return False, "未命中民族相关关键词，需人工复核"
