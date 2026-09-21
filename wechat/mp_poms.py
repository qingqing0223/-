"""POMS table 1–5 wire format from the repository's batch API guide.

Unknown values remain null even where the example data uses zero. Pending
review maps to a null boolean plus its reason; it must never become false.
"""
from __future__ import annotations

import json

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
    "matched_keywords为数组，明确有效/无效为true/false，待核验为null且保留具体原因；CSV/XLSX仍显示待核验。"
    "未取得的账号ID和指标保留null，空评论表为[]。接口示例中的0不替代未知值。"
    "服务端必须支持这些null；文档未明确其可空约束，若拒收须调整服务端，不能伪造账号ID或将未知值改为0。"
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
                obj[field] = {"是": True, "否": False, "待核验": None, None: None}[obj[field]]
        result.append(obj)
    return result
