from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from monitor.zhihu_submission import export_zhihu_submission


KEYWORDS = [
    "2026年民族团结进步宣传周",
    "首个民族团结进步宣传周",
    "促进民族团结进步，奋进伟大复兴征程",
    "民族团结进步倡议",
    "民族团结进步宣传周主场活动",
    "石榴花开——铸牢中华民族共同体意识",
]


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_catalog(root: Path) -> None:
    path = root / "config" / "key_accounts.v3.catalog.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "categories": [
                    {
                        "account_type": "中央媒体",
                        "accounts": ["人民日报", "新华社"],
                    },
                    {
                        "account_type": "统战系统媒体",
                        "accounts": ["国家民委"],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _cfg() -> dict:
    return {
        "keywords": KEYWORDS,
        "monitoring_start_time": "2026-09-16T00:00:00+08:00",
        "key_account_catalog": "config/key_accounts.v3.catalog.json",
    }


def test_exports_only_tables_1_to_5_with_strict_scope_and_dedupe(tmp_path):
    _write_catalog(tmp_path)
    raw = tmp_path / "zhihu_real_shape.jsonl"
    rows = [
        {
            "content_id": "10001",
            "content_type": "answer",
            "title": "首个民族团结进步宣传周将于9月21日至27日举办",
            "content_text": "2026 年民族团结进步宣传周聚焦促进民族团结进步，奋进伟大复兴征程。",
            "content_url": "https://www.zhihu.com/question/1/answer/10001",
            "created_time": "2026-09-17T08:00:00+08:00",
            "source_keyword": KEYWORDS[0],
            "creator_hash": "90001",
            "user_nickname": "人民日报",
            "voteup_count": 12,
            "comment_count": 2,
            "ip_location": "北京",
        },
        {
            # Same content found by a second keyword. It must merge, not duplicate.
            "content_id": "10001",
            "content_type": "answer",
            "title": "首个民族团结进步宣传周将于9月21日至27日举办",
            "content_text": "2026年民族团结进步宣传周聚焦促进民族团结进步，奋进伟大复兴征程。",
            "content_url": "https://www.zhihu.com/question/1/answer/10001",
            "created_time": "2026-09-17T08:00:00+08:00",
            "source_keyword": KEYWORDS[2],
            "creator_hash": "90001",
            "user_nickname": "人民日报",
            "voteup_count": 15,
            "comment_count": 2,
            "ip_location": "北京",
        },
        {
            "content_id": "old",
            "title": "2026年民族团结进步宣传周",
            "content_text": "旧内容",
            "created_time": "2026-09-15T23:59:59+08:00",
            "creator_hash": "old-a",
            "user_nickname": "旧账号",
        },
        {
            # Wide words only: should not pass the six-complete-keyword rule.
            "content_id": "loose",
            "title": "某地民族团结活动宣传周",
            "content_text": "仅有民族团结和宣传周这些宽泛词",
            "created_time": "2026-09-17T10:00:00+08:00",
            "creator_hash": "loose-a",
            "user_nickname": "普通用户",
        },
        {
            "content_id": "missing-time",
            "title": "2026年民族团结进步宣传周",
            "content_text": "发布时间未知",
            "creator_hash": "x",
            "user_nickname": "普通用户",
        },
        {
            "content_id": "10001",
            "comment_id": "c001",
            "content": "一级评论",
            "publish_time": "2026-09-17T09:00:00+08:00",
            "like_count": 3,
            "sub_comment_count": 1,
            "creator_hash": "u1",
            "user_nickname": "用户甲",
            "ip_location": "河北",
        },
        {
            "content_id": "10001",
            "comment_id": "c002",
            "parent_comment_id": "c001",
            "root_comment_id": "c001",
            "content": "楼中楼回复",
            "publish_time": "2026-09-17T09:05:00+08:00",
            "creator_hash": "u2",
            "user_nickname": "用户乙",
        },
        {
            "content_id": "loose",
            "comment_id": "bad-c",
            "content": "父内容无效，因此该评论也不能进入正式数据",
            "publish_time": "2026-09-17T10:05:00+08:00",
            "creator_hash": "u3",
            "user_nickname": "用户丙",
        },
    ]
    raw.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    result = export_zhihu_submission(
        [raw],
        _cfg(),
        tmp_path,
        "zhihu01",
        now=datetime(
            2026,
            9,
            20,
            16,
            10,
            tzinfo=timezone(timedelta(hours=8)),
        ),
    )

    output = (
        tmp_path
        / "data_submissions"
        / "zhihu"
        / "2026-09-20_zhihu01"
    )
    table1 = _read_jsonl(output / "table1_content.jsonl")
    table2 = _read_jsonl(output / "table2_comments.jsonl")
    table3 = _read_jsonl(output / "table3_content_engagement.jsonl")
    table4 = _read_jsonl(output / "table4_comment_engagement.jsonl")
    table5 = _read_jsonl(output / "table5_accounts.jsonl")

    assert len(table1) == 1
    assert table1[0]["content_id"] == "10001"
    assert set(table1[0]["matched_keywords"]) >= {
        KEYWORDS[0],
        KEYWORDS[2],
    }
    assert len(table2) == 2
    assert {row["comment_id"] for row in table2} == {"c001", "c002"}
    assert next(
        row for row in table2 if row["comment_id"] == "c002"
    )["comment_level"] == 2
    assert len(table3) == 1
    assert table3[0]["like_count"] == 15
    assert len(table4) == 2

    assert len(table5) == 1
    assert table5[0]["is_key_account"] is True
    assert table5[0]["account_type"] == "中央媒体"
    # Zhihu did not expose repost/favorite in this fixture; keep blank, not 0.
    assert table5[0]["repost_count"] == ""
    assert table5[0]["total_engagement"] == ""

    assert result["classification"] == "not_run_collection_group_scope_only"
    assert result["excluded_rows"] == 4
    assert result["table12_update_policy_seconds"] == 900
    assert result["table345_update_policy_seconds"] == 3600


def test_tables_3_to_5_update_only_once_per_hour(tmp_path):
    _write_catalog(tmp_path)
    raw = tmp_path / "contents.jsonl"
    raw.write_text(
        json.dumps(
            {
                "content_id": "10001",
                "content_type": "answer",
                "title": "2026年民族团结进步宣传周",
                "content_text": "2026年民族团结进步宣传周",
                "created_time": "2026-09-17T08:00:00+08:00",
                "creator_hash": "90001",
                "user_nickname": "人民日报",
                "voteup_count": 12,
                "comment_count": 2,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    tz = timezone(timedelta(hours=8))
    export_zhihu_submission(
        [raw],
        _cfg(),
        tmp_path,
        "zhihu01",
        now=datetime(2026, 9, 20, 16, 10, tzinfo=tz),
    )
    output = (
        tmp_path
        / "data_submissions"
        / "zhihu"
        / "2026-09-20_zhihu01"
    )
    assert len(_read_jsonl(output / "table3_content_engagement.jsonl")) == 1

    result_same_hour = export_zhihu_submission(
        [raw],
        _cfg(),
        tmp_path,
        "zhihu01",
        now=datetime(2026, 9, 20, 16, 25, tzinfo=tz),
    )
    assert result_same_hour["hourly_snapshot_due"] is False
    assert len(_read_jsonl(output / "table3_content_engagement.jsonl")) == 1

    result_next_hour = export_zhihu_submission(
        [raw],
        _cfg(),
        tmp_path,
        "zhihu01",
        now=datetime(2026, 9, 20, 17, 1, tzinfo=tz),
    )
    assert result_next_hour["hourly_snapshot_due"] is True
    assert len(_read_jsonl(output / "table3_content_engagement.jsonl")) == 2