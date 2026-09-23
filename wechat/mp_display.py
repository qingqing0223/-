"""Submission-only placeholders. Never mutate crawler records or evidence."""
from __future__ import annotations

from copy import deepcopy
import hashlib

from .mp_records import normalize_name

ZERO_NOTE = "0表示当前公开数据源未取得对应统计指标，不等同于平台真实值为0。"
INTERACTION_NOTE = "微信公众号搜狗公开搜索源当前无法可靠取得文章阅读、点赞、评论、转发、分享、收藏量。本表中对应的0为系统接口占位值，不代表平台真实互动量为0。"
ACCOUNT_ID_NOTE = "local_wxacct_* 为本系统内部关联ID，并非微信官方帐号ID。基于规范化帐号名称稳定生成；优先使用有公开证据的官方ID，不从名称猜测机构或地区。"
COMMENT_NOTE = "微信公众号当前公开搜索数据源未取得公开评论/楼中楼，故表2、表4本批次记录数为0。"
RAW_NOTE = "展示/提交标准化仅作用于Excel、CSV和POMS JSON。原始search_contents.jsonl继续保留null及缺失状态；未知数值的0占位不参与原始证据和可靠互动汇总。"


def empty(value) -> bool:
    return value is None or isinstance(value, str) and not value.strip()


def account_key(name, official_id=None) -> str:
    if not empty(official_id) and not str(official_id).startswith("local_wxacct_"):
        return str(official_id)
    normalized = normalize_name(name or "")
    if not normalized or normalized in ("未获取", "未知"):
        return "未获取"  # Do not merge unrelated anonymous accounts under an invented identity.
    return "local_wxacct_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def normalize_tables(tables: list[list[list]]) -> list[list[list]]:
    result = deepcopy(tables)
    official = {}
    for row in result[0]:
        if not empty(row[2]) and not str(row[2]).startswith("local_wxacct_") and row[2] != "未获取":
            name = normalize_name(row[3] or "")
            if name in official and official[name] != str(row[2]):
                raise ValueError("Conflicting official IDs for the same normalized account name")
            if name:
                official[name] = str(row[2])
    for row in result[4]:
        if not empty(row[0]) and not str(row[0]).startswith("local_wxacct_") and row[0] != "未获取":
            name = normalize_name(row[2] or "")
            if name in official and official[name] != str(row[0]):
                raise ValueError("Conflicting account IDs between tables 1 and 5")
            if name:
                official[name] = str(row[0])
    for row in result[0]:
        row[2] = account_key(row[3], official.get(normalize_name(row[3] or "")))
        for index, value in {4: "平台公开数据源暂不提供", 5: "未识别", 8: "公开搜索结果未提供正文摘要", 13: "未知", 15: "无" if row[14] == "是" else "缺少明确有效性依据，待人工核验"}.items():
            if empty(row[index]):
                row[index] = value
    for row in result[4]:
        row[0] = account_key(row[2], official.get(normalize_name(row[2] or "")))
        if empty(row[4]):
            row[4] = "未识别"
    numeric_columns = {2: range(3, 9), 3: range(4, 6), 4: [5, 6, *range(10, 17)]}
    for index, table in enumerate(result):
        for row in table:
            for col, value in enumerate(row):
                if col in numeric_columns.get(index, ()):
                    if empty(value):
                        row[col] = 0
                    elif type(value) is not int or value < 0:
                        raise ValueError("Submission statistics must be nonnegative integers")
                elif empty(value):
                    row[col] = "未获取"
    return result


def audit_tables(tables, fields, sheets) -> list[dict]:
    return [{"sheet": sheet, "field": field, "empty_count": sum(empty(row[col]) for row in table)}
            for table, names, sheet in zip(tables, fields, sheets) for col, field in enumerate(names)]


def placeholder_counts(raw_tables, fields, sheets) -> list[dict]:
    return [{"sheet": sheet, "field": field, "missing_source_count": sum(empty(row[col]) for row in table)}
            for table, names, sheet in zip(raw_tables, fields, sheets) for col, field in enumerate(names)
            if any(empty(row[col]) for row in table)]
