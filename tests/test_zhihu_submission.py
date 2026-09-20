import json

from monitor.zhihu_submission import export_zhihu_submission


KEYWORDS = ["2026年民族团结进步宣传周", "首个民族团结进步宣传周"]


def test_exports_parent_and_nested_comment_without_classification(tmp_path):
    raw = tmp_path / "search_contents.jsonl"
    comment = tmp_path / "detail_comments.jsonl"
    raw.write_text(json.dumps({
        "content_id": "001", "content_type": "answer", "title": "2026年民族团结进步宣传周活动",
        "content_text": "活动介绍", "content_url": "https://www.zhihu.com/question/x/answer/001",
        "created_time": "2026-09-17T08:00:00+08:00", "source_keyword": KEYWORDS[0],
        "creator_hash": "author-001", "user_nickname": "账号", "voteup_count": 3, "comment_count": 1,
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    comment.write_text(json.dumps({
        "content_id": "001", "comment_id": "002", "parent_comment_id": "0010", "content": "回复内容",
        "publish_time": "2026-09-17T09:00:00+08:00", "like_count": 2, "sub_comment_count": 0,
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    result = export_zhihu_submission([raw, comment], {
        "keywords": KEYWORDS, "monitoring_start_time": "2026-09-16T00:00:00+08:00"
    }, tmp_path, "zhihu01")
    out = tmp_path / "data_submissions" / "zhihu" / "zhihu01"
    date_dir = next(out.iterdir())
    content = json.loads((date_dir / "table1_content.jsonl").read_text(encoding="utf-8"))
    comments = json.loads((date_dir / "table2_comments.jsonl").read_text(encoding="utf-8"))
    assert content["content_id"] == "001"
    assert comments["comment_id"] == "002"
    assert comments["parent_comment_id"] == "0010"
    assert result["classification"] == "not_run_collection_group_scope_only"
