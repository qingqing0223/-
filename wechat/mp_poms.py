"""POMS table 1–5 wire format from the repository's batch API guide.

Display placeholders follow the approved submission policy; raw data stays null.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

TABLE_NAMES = [
    "published_content_basic_information", "comment_basic_information",
    "published_content_interaction_data", "comment_content_interaction_data",
    "account_information",
]
POMS_FIELDS = [
    ["published_content_id", "platform_name", "publisher_account_id", "account_name", "account_ip_location", "account_type", "content_type", "title", "body_text_or_video_description", "published_at", "collected_at", "original_content_url", "matched_keywords", "originality_status", "is_valid_monitoring_data", "invalid_reason"],
    ["corresponding_published_content_id", "comment_id", "platform_name", "commenter_user_id", "commenter_ip_location", "comment_text", "commented_at", "is_valid_comment"],
    ["corresponding_published_content_id", "platform_name", "statistical_time", "view_or_play_count", "like_count", "comment_count", "repost_count", "share_count", "favorite_count"],
    ["corresponding_published_content_id", "comment_id", "platform_name", "statistical_time", "comment_reply_count", "comment_like_count"],
    ["account_id", "platform", "account_name", "homepage_url", "account_type", "follower_count", "following_count", "region", "organization", "is_key_monitored_account", "related_post_count", "view_or_play_count", "like_count", "comment_count", "repost_count", "favorite_count", "total_interaction_count", "collected_at"],
]
POMS_NOTE = (
    "table1_batch.json至table5_batch.json按POMS批量接口的英文键名和字段顺序输出JSON数组。"
    "matched_keywords为数组，明确有效为true，明确无效为false。经用户确认，待核验在POMS中用false表示尚未确认为有效，invalid_reason保留待核验原因；CSV/XLSX仍显示待核验。"
    "缺失统计使用数值0占位，缺失文本使用明确状态值；local_wxacct_*为本地关联ID，空评论表为[]。原始证据层不改变。"
)


def poms_rows(index: int, rows: list[list]) -> list[dict]:
    result = []
    for values in rows:
        if len(values) != len(POMS_FIELDS[index]):
            raise ValueError("POMS row has unexpected field count")
        obj = dict(zip(POMS_FIELDS[index], [None if v == "" else v for v in values]))
        if index == 0:
            obj["matched_keywords"] = json.loads(obj["matched_keywords"]) if isinstance(obj["matched_keywords"], str) else obj["matched_keywords"]
        for field in ("is_valid_monitoring_data", "is_valid_comment", "is_key_monitored_account"):
            if field in obj:
                if obj[field] not in ("是", "否", "待核验", None):
                    raise ValueError(f"{field}: unexpected validity label")
                obj[field] = {"是": True, "否": False, "待核验": False, None: None}[obj[field]]
        result.append(obj)
    return result


def validate_schema(arrays: list[list[dict]]) -> None:
    """Validate against the inspected public OpenAPI subset, without a network call."""
    source = Path(__file__).resolve().parents[1] / "config/poms.wechat_mp.schema.json"
    schemas = json.loads(source.read_text(encoding="utf-8"))["schemas"]
    names = ["PublishedContentBasicInformation", "CommentBasicInformation", "PublishedContentInteractionData", "CommentContentInteractionData", "AccountInformation"]

    def matches(value, schema):
        if "anyOf" in schema:
            return any(matches(value, option) for option in schema["anyOf"])
        kind = schema.get("type")
        if kind == "null":
            return value is None
        if kind == "string":
            if not isinstance(value, str) or not value.strip():
                return False
            if schema.get("format") == "date-time":
                try:
                    if datetime.fromisoformat(value).tzinfo is None:
                        return False
                except ValueError:
                    return False
        elif kind == "integer":
            if type(value) is not int or value < schema.get("minimum", 0):
                return False
        elif kind == "boolean":
            if type(value) is not bool:
                return False
        elif kind == "array":
            if not isinstance(value, list) or not all(matches(v, schema["items"]) for v in value):
                return False
        else:
            raise ValueError("Unsupported constraint in cached POMS schema")
        return "enum" not in schema or value in schema["enum"]

    for number, (rows, name, fields) in enumerate(zip(arrays, names, POMS_FIELDS), 1):
        schema = schemas[name]
        if list(schema["properties"]) != fields:
            raise ValueError("POMS schema order changed; review adapter before upload")
        for index, row in enumerate(rows, 1):
            if list(row) != fields:
                raise ValueError(f"table{number}: wrong field order")
            for field, value in row.items():
                if not matches(value, schema["properties"][field]):
                    raise ValueError(f"后端schema与大屏无空值要求冲突或字段值不合法: table{number} row={index} field={field}")
                if value is None or isinstance(value, str) and not value.strip():
                    raise ValueError(f"后端schema与大屏无空值要求冲突: table{number} row={index} field={field}")
