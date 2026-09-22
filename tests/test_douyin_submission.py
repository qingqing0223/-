import json
from datetime import datetime
from pathlib import Path

from monitor.douyin_submission import (
    BEIJING,
    export_douyin_submission,
)


def write_jsonl(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path):
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def base_config():
    return {
        "keywords": [
            "2026年民族团结进步宣传周",
            "首个民族团结进步宣传周",
        ],
        "monitoring_start_time": "2026-09-16T00:00:00+08:00",
        "douyin_submission_require_topic": True,
    }


def cycle_rows(like_count=20, comment_like=3):
    return [
        {
            "aweme_id": "1001",
            "desc": "2026年民族团结进步宣传周将于9月21日启动",
            "nickname": "测试发布账号",
            "creator_hash": "author001",
            "publish_time": "2026-09-20T08:00:00Z",
            "liked_count": 10,
            "comment_count": 5,
            "share_count": 26,
            "collected_count": 7,
            "source_keyword": "2026年民族团结进步宣传周",
        },
        {
            # 同一个内容由第二个关键词再次命中，
            # 用于验证“全部命中关键词”能够合并。
            "aweme_id": "1001",
            "desc": "首个民族团结进步宣传周将于9月21日启动",
            "nickname": "测试发布账号",
            "creator_hash": "author001",
            "publish_time": "2026-09-20T08:00:00Z",
            "liked_count": like_count,
            "comment_count": 5,
            "share_count": 30,
            "collected_count": 8,
            "source_keyword": "首个民族团结进步宣传周",
        },
        {
            "aweme_id": "1001",
            "comment_id": "2001",
            "content": "支持宣传周活动",
            "nickname": "测试评论账号",
            "publish_time": "2026-09-20T09:30:00Z",
            "like_count": comment_like,
            "sub_comment_count": 1,
        },
    ]


def test_douyin_submission_hourly_keywords_share_and_timezone(tmp_path):
    raw1 = tmp_path / "raw1.jsonl"
    write_jsonl(raw1, cycle_rows())

    result1 = export_douyin_submission(
        [raw1],
        base_config(),
        tmp_path,
        "dy01",
        now=datetime(2026, 9, 20, 17, 15, tzinfo=BEIJING),
    )

    out = Path(result1["output_directory"])

    t1 = read_jsonl(out / "table1_content.jsonl")
    t2 = read_jsonl(out / "table2_comments.jsonl")
    t3 = read_jsonl(out / "table3_content_engagement.jsonl")
    t4 = read_jsonl(out / "table4_comment_engagement.jsonl")
    t5 = read_jsonl(out / "table5_accounts.jsonl")

    assert len(t1) == 1
    assert len(t2) == 1
    assert len(t3) == 1
    assert len(t4) == 1
    assert len(t5) == 1

    assert set(t1[0]["matched_keywords"]) == {
        "2026年民族团结进步宣传周",
        "首个民族团结进步宣传周",
    }

    # UTC 08:00 -> 北京时间16:00
    assert t1[0]["publish_time"] == "2026-09-20T16:00:00+08:00"

    # UTC 09:30 -> 北京时间17:30
    assert t2[0]["comment_publish_time"] == "2026-09-20T17:30:00+08:00"

    assert t3[0]["snapshot_hour"] == "2026-09-20T17:00:00+08:00"

    # 抖音raw只提供share_count：
    # 分享量有值，独立转发量必须为空。
    assert t3[0]["share_count"] == 30
    assert t3[0]["repost_count"] == ""

    # 同一小时再次刷新，只更新当前小时，不新增第二条历史。
    raw2 = tmp_path / "raw2.jsonl"
    write_jsonl(raw2, cycle_rows(like_count=99, comment_like=8))

    export_douyin_submission(
        [raw2],
        base_config(),
        tmp_path,
        "dy01",
        now=datetime(2026, 9, 20, 17, 45, tzinfo=BEIJING),
    )

    t3 = read_jsonl(out / "table3_content_engagement.jsonl")
    t4 = read_jsonl(out / "table4_comment_engagement.jsonl")

    assert len(t3) == 1
    assert len(t4) == 1
    assert t3[0]["like_count"] == 99
    assert t4[0]["comment_like_count"] == 8

    # 下一小时再次采集，必须追加历史，而不是覆盖17点快照。
    export_douyin_submission(
        [raw2],
        base_config(),
        tmp_path,
        "dy01",
        now=datetime(2026, 9, 20, 18, 5, tzinfo=BEIJING),
    )

    t3 = read_jsonl(out / "table3_content_engagement.jsonl")
    t4 = read_jsonl(out / "table4_comment_engagement.jsonl")

    assert len(t3) == 2
    assert len(t4) == 2

    assert {
        row["snapshot_hour"]
        for row in t3
    } == {
        "2026-09-20T17:00:00+08:00",
        "2026-09-20T18:00:00+08:00",
    }


def test_douyin_submission_rejects_obvious_topic_false_positives(tmp_path):
    raw = tmp_path / "topic.jsonl"

    write_jsonl(
        raw,
        [
            {
                "aweme_id": "bad-law",
                "desc": "民族团结进步促进法第十一条公益普法",
                "publish_time": "2026-09-20T08:00:00Z",
                "source_keyword": "2026年民族团结进步宣传周",
            },
            {
                "aweme_id": "bad-month",
                "desc": "民族团结宣传月 盛世华诞谱新篇",
                "publish_time": "2026-09-20T08:00:00Z",
                "source_keyword": "2026年民族团结进步宣传周",
            },
            {
                "aweme_id": "bad-short-tags",
                "desc": "#民族团结#进步#宣传周#",
                "publish_time": "2026-09-20T08:00:00Z",
                "source_keyword": "2026年民族团结进步宣传周",
            },
            {
                "aweme_id": "good",
                "desc": "玉溪市2026年民族团结进步宣传周系列活动启动",
                "publish_time": "2026-09-20T08:00:00Z",
                "source_keyword": "2026年民族团结进步宣传周",
            },
        ],
    )

    result = export_douyin_submission(
        [raw],
        base_config(),
        tmp_path,
        "dy01",
        now=datetime(2026, 9, 20, 19, 0, tzinfo=BEIJING),
    )

    rows = read_jsonl(
        Path(result["output_directory"]) / "table1_content.jsonl"
    )

    assert [row["content_id"] for row in rows] == ["good"]



def test_douyin_submission_recovers_collection_time_from_raw_run_path(tmp_path):
    raw1 = (
        tmp_path
        / "raw_runs"
        / "20260920_171500"
        / "dy_run"
        / "douyin"
        / "jsonl"
        / "search_contents_2026-09-20.jsonl"
    )

    raw2 = (
        tmp_path
        / "raw_runs"
        / "20260920_180500"
        / "dy_run"
        / "douyin"
        / "jsonl"
        / "search_contents_2026-09-20.jsonl"
    )

    write_jsonl(raw1, cycle_rows(like_count=20, comment_like=3))
    write_jsonl(raw2, cycle_rows(like_count=99, comment_like=8))

    result = export_douyin_submission(
        [raw1, raw2],
        base_config(),
        tmp_path,
        "dy01",
        now=datetime(2026, 9, 20, 20, 0, tzinfo=BEIJING),
    )

    out = Path(result["output_directory"])

    t1 = read_jsonl(out / "table1_content.jsonl")
    t2 = read_jsonl(out / "table2_comments.jsonl")
    t3 = read_jsonl(out / "table3_content_engagement.jsonl")
    t4 = read_jsonl(out / "table4_comment_engagement.jsonl")
    t5 = read_jsonl(out / "table5_accounts.jsonl")

    assert len(t1) == 1
    assert len(t2) == 1
    assert len(t3) == 2
    assert len(t4) == 2
    assert len(t5) == 1

    # 表1保留该内容最近一次真实采集批次时间。
    assert t1[0]["collection_time"] == "2026-09-20T18:05:00+08:00"

    # 表2同样保留该评论最近一次真实采集批次时间。
    assert t2[0]["collection_time"] == "2026-09-20T18:05:00+08:00"

    # 表3必须恢复两个真实历史小时，而不是用now=20:00伪造快照。
    assert {
        row["snapshot_time"]
        for row in t3
    } == {
        "2026-09-20T17:15:00+08:00",
        "2026-09-20T18:05:00+08:00",
    }

    assert {
        row["snapshot_hour"]
        for row in t3
    } == {
        "2026-09-20T17:00:00+08:00",
        "2026-09-20T18:00:00+08:00",
    }

    # 表4评论互动快照也必须保留两个小时。
    assert {
        row["snapshot_time"]
        for row in t4
    } == {
        "2026-09-20T17:15:00+08:00",
        "2026-09-20T18:05:00+08:00",
    }

    # 17点和18点的互动数据分别保留下来。
    t3_by_hour = {
        row["snapshot_hour"]: row
        for row in t3
    }

    assert (
        t3_by_hour["2026-09-20T17:00:00+08:00"]["like_count"]
        == 20
    )
    assert (
        t3_by_hour["2026-09-20T18:00:00+08:00"]["like_count"]
        == 99
    )

    t4_by_hour = {
        row["snapshot_hour"]: row
        for row in t4
    }

    assert (
        t4_by_hour["2026-09-20T17:00:00+08:00"]["comment_like_count"]
        == 3
    )
    assert (
        t4_by_hour["2026-09-20T18:00:00+08:00"]["comment_like_count"]
        == 8
    )

    # 表5取该账号最新已有真实互动快照的时间。
    assert t5[0]["collection_time"] == "2026-09-20T18:05:00+08:00"



def test_douyin_submission_keeps_empty_text_public_comments(tmp_path):
    raw = (
        tmp_path
        / "raw_runs"
        / "20260920_210000"
        / "dy"
        / "douyin"
        / "jsonl"
        / "detail_comments.jsonl"
    )

    write_jsonl(
        raw,
        [
            {
                "aweme_id": "1001",
                "desc": "2026年民族团结进步宣传周活动启动",
                "nickname": "发布账号",
                "creator_hash": "author001",
                "publish_time": "2026-09-20T08:00:00Z",
                "source_keyword": "2026年民族团结进步宣传周",
            },
            {
                "aweme_id": "1001",
                "comment_id": "empty-parent",
                "parent_comment_id": 0,
                "content": "",
                "pictures": "",
                "nickname": "空正文用户",
                "creator_hash": "u1",
                "ip_location": "四川",
                "publish_time": "2026-09-20T09:00:00Z",
            },
            {
                "aweme_id": "1001",
                "comment_id": "picture-comment",
                "parent_comment_id": 0,
                "content": "",
                "pictures": "https://example.invalid/image.jpg",
                "nickname": "图片用户",
                "creator_hash": "u2",
                "ip_location": "云南",
                "publish_time": "2026-09-20T09:05:00Z",
            },
            {
                "aweme_id": "1001",
                "comment_id": "reply1",
                "parent_comment_id": "empty-parent",
                "content": "二级回复",
                "nickname": "回复用户",
                "creator_hash": "u3",
                "ip_location": "甘肃",
                "publish_time": "2026-09-20T09:10:00Z",
            },
        ],
    )

    result = export_douyin_submission(
        [raw],
        base_config(),
        tmp_path,
        "dy01",
        now=datetime(2026, 9, 20, 21, 0, tzinfo=BEIJING),
    )

    out = Path(result["output_directory"])
    comments = read_jsonl(out / "table2_comments.jsonl")

    by_id = {
        row["comment_id"]: row
        for row in comments
    }

    assert set(by_id) == {
        "empty-parent",
        "picture-comment",
        "reply1",
    }

    assert by_id["empty-parent"]["comment_text"] == ""
    assert by_id["empty-parent"]["comment_user_ip_location"] == "四川"

    assert by_id["picture-comment"]["comment_text"] == ""
    assert (
        by_id["picture-comment"]["comment_pictures"]
        == "https://example.invalid/image.jpg"
    )

    assert (
        by_id["reply1"]["parent_comment_id"]
        == "empty-parent"
    )



def test_douyin_submission_uses_ip_enrichment_without_overwriting_raw(
    tmp_path,
):
    raw = (
        tmp_path
        / "raw_runs"
        / "20260920_210000"
        / "dy"
        / "douyin"
        / "jsonl"
        / "detail_comments.jsonl"
    )

    write_jsonl(
        raw,
        [
            {
                "aweme_id": "1001",
                "desc": "2026年民族团结进步宣传周活动",
                "nickname": "发布账号",
                "creator_hash": "author001",
                "publish_time": "2026-09-20T08:00:00Z",
                "source_keyword": "2026年民族团结进步宣传周",
            },
            {
                "aweme_id": "1001",
                "comment_id": "comment-enriched",
                "content": "历史评论",
                "nickname": "用户1",
                "creator_hash": "u1",
                "publish_time": "2026-09-20T09:00:00Z",
            },
            {
                "aweme_id": "1001",
                "comment_id": "comment-raw",
                "content": "新评论",
                "nickname": "用户2",
                "creator_hash": "u2",
                "ip_location": "广东",
                "publish_time": "2026-09-20T09:05:00Z",
            },
            {
                "aweme_id": "1001",
                "comment_id": "comment-missing",
                "content": "无公开地区",
                "nickname": "用户3",
                "creator_hash": "u3",
                "publish_time": "2026-09-20T09:10:00Z",
            },
        ],
    )

    enrichment = tmp_path / "classified_results.jsonl"

    write_jsonl(
        enrichment,
        [
            {
                "record_type": "comment",
                "comment_id": "comment-enriched",
                "ip_location": "湖南",
            },
            {
                "record_type": "comment",
                "comment_id": "comment-raw",
                "ip_location": "北京",
            },
        ],
    )

    cfg = base_config()
    cfg["douyin_submission_enrichment_jsonl"] = str(
        enrichment
    )

    result = export_douyin_submission(
        [raw],
        cfg,
        tmp_path,
        "dy01",
        now=datetime(
            2026,
            9,
            20,
            21,
            0,
            tzinfo=BEIJING,
        ),
    )

    rows = read_jsonl(
        Path(result["output_directory"])
        / "table2_comments.jsonl"
    )

    by_id = {
        row["comment_id"]: row
        for row in rows
    }

    assert (
        by_id["comment-enriched"][
            "comment_user_ip_location"
        ]
        == "湖南"
    )

    # raw已有IP时，raw优先，不能被旧enrichment覆盖
    assert (
        by_id["comment-raw"][
            "comment_user_ip_location"
        ]
        == "广东"
    )

    # 两边都没有时必须继续为空
    assert (
        by_id["comment-missing"][
            "comment_user_ip_location"
        ]
        == ""
    )



def test_douyin_submission_requires_visible_keyword_evidence(
    tmp_path,
):
    raw = (
        tmp_path
        / "raw_runs"
        / "20260921_111500"
        / "dy"
        / "douyin"
        / "jsonl"
        / "search_contents_2026-09-21.jsonl"
    )

    write_jsonl(
        raw,
        [
            {
                "aweme_id": "topic-fuzzy-only",
                "desc": "\u5404\u6c11\u65cf\u540c\u5fc3\u76f8\u4f9d\uff0c\u5c71\u6cb3\u9526\u7ee3\u56fd\u6cf0\u6c11\u5b89 #\u6c11\u65cf\u5927\u56e2\u7ed3 #\u5bb6\u56fd\u60c5\u6000",
                "nickname": "\u7528\u62371",
                "creator_hash": "u1",
                "publish_time": "2026-09-21T03:04:31Z",
                "source_keyword": "\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65\u5ba3\u4f20\u5468\u4e3b\u9898\u5ba3\u4f20\u7247",
            },
            {
                "aweme_id": "topic-exact-initiative",
                "desc": "\u4eca\u65e5\u53d1\u5e03\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65\u5021\u8bae\uff0c\u5021\u5bfc\u4ea4\u5f80\u4ea4\u6d41\u4ea4\u878d\u3002",
                "nickname": "\u7528\u62372",
                "creator_hash": "u2",
                "publish_time": "2026-09-21T03:05:00Z",
                "source_keyword": "\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65\u5021\u8bae",
            },
            {
                "aweme_id": "topic-exact-slogan",
                "desc": "\u4fc3\u8fdb\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65\uff0c\u594b\u8fdb\u4f1f\u5927\u590d\u5174\u5f81\u7a0b\u3002",
                "nickname": "\u7528\u62373",
                "creator_hash": "u3",
                "publish_time": "2026-09-21T03:06:00Z",
                "source_keyword": "\u4fc3\u8fdb\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65\uff0c\u594b\u8fdb\u4f1f\u5927\u590d\u5174\u5f81\u7a0b",
            },
        ],
    )

    cfg = base_config()
    cfg["monitoring_start_time"] = (
        "2026-09-21T09:00:00+08:00"
    )
    cfg["keywords"] = [
        "\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65\u5021\u8bae",
        "2026\u5e74\u6c11\u65cf\u5ba3\u4f20\u5468\u4e3b\u573a\u6d3b\u52a8",
        "\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65\u5ba3\u4f20\u5468\u4e3b\u9898\u5ba3\u4f20\u7247",
        "\u4fc3\u8fdb\u6c11\u65cf\u56e2\u7ed3\u8fdb\u6b65\uff0c\u594b\u8fdb\u4f1f\u5927\u590d\u5174\u5f81\u7a0b",
    ]

    result = export_douyin_submission(
        [raw],
        cfg,
        tmp_path,
        "dy01",
        now=datetime(
            2026,
            9,
            21,
            11,
            15,
            tzinfo=BEIJING,
        ),
    )

    rows = read_jsonl(
        Path(result["output_directory"])
        / "table1_content.jsonl"
    )

    ids = {
        str(row["content_id"])
        for row in rows
    }

    # Search provenance alone must NOT admit fuzzy search results.
    assert "topic-fuzzy-only" not in ids

    # Exact visible monitoring phrases are valid topic evidence.
    assert "topic-exact-initiative" in ids
    assert "topic-exact-slogan" in ids
