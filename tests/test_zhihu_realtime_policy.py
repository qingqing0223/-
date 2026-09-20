from __future__ import annotations

import json
from pathlib import Path

import monitor.crawler_runner as crawler_runner
from monitor.zhihu_realtime_policy import (
    SCOPE_POLICY_VERSION,
    install_zhihu_scope_aware_realtime_policy,
)


KEYWORDS = [
    "2026年民族团结进步宣传周",
    "首个民族团结进步宣传周",
    "促进民族团结进步，奋进伟大复兴征程",
    "民族团结进步倡议",
    "民族团结进步宣传周主场活动",
    "石榴花开——铸牢中华民族共同体意识",
]


def _cfg() -> dict:
    return {
        "keywords": KEYWORDS,
        "monitoring_start_time": "2026-09-16T00:00:00+08:00",
        "zhihu_require_publish_time": True,
    }


def _install_for_test():
    marker = "_promotion_week_zhihu_scope_aware_realtime_policy"
    original_update = crawler_runner._update_queue_from_content
    original_classify = crawler_runner._classify_state
    if hasattr(crawler_runner, marker):
        delattr(crawler_runner, marker)
    install_zhihu_scope_aware_realtime_policy(_cfg())
    return marker, original_update, original_classify


def _restore(marker, original_update, original_classify):
    crawler_runner._update_queue_from_content = original_update
    crawler_runner._classify_state = original_classify
    if hasattr(crawler_runner, marker):
        delattr(crawler_runner, marker)


def test_zhihu_queue_keeps_only_formally_in_scope_content(tmp_path: Path):
    marker, original_update, original_classify = _install_for_test()
    try:
        raw = tmp_path / "search_contents.jsonl"
        rows = [
            {
                "content_id": "valid",
                "content_url": "https://www.zhihu.com/question/1/answer/valid",
                "title": "2026年民族团结进步宣传周",
                "content_text": "首个民族团结进步宣传周",
                "created_time": "2026-09-20T10:00:00+08:00",
                "comment_count": 3,
            },
            {
                "content_id": "old",
                "content_url": "https://www.zhihu.com/question/1/answer/old",
                "title": "2026年民族团结进步宣传周",
                "content_text": "旧内容",
                "created_time": "2026-09-15T23:59:59+08:00",
                "comment_count": 100,
            },
            {
                "content_id": "wide",
                "content_url": "https://www.zhihu.com/question/1/answer/wide",
                "title": "民族团结活动宣传周",
                "content_text": "只命中宽泛词",
                "created_time": "2026-09-20T10:00:00+08:00",
                "comment_count": 50,
            },
        ]
        raw.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )
        queue = {
            "version": 1,
            "items": {
                "https://www.zhihu.com/question/old/answer/stale": {
                    "visible_comment_count": 999,
                    "retry_count": 5,
                }
            },
        }

        crawler_runner._update_queue_from_content("zhihu", [raw], queue)

        assert set(queue["items"]) == {
            "https://www.zhihu.com/question/1/answer/valid"
        }
        item = next(iter(queue["items"].values()))
        assert item["scope_policy_version"] == SCOPE_POLICY_VERSION
        assert item["scope_validated"] is True
        assert item["visible_comment_count"] == 3
        assert item["comment_count_unknown"] is False
        assert item["matched_keywords"]
    finally:
        _restore(marker, original_update, original_classify)


def test_zhihu_unknown_comment_count_gets_queue_only_sentinel(tmp_path: Path):
    marker, original_update, original_classify = _install_for_test()
    try:
        raw = tmp_path / "search_contents.jsonl"
        raw.write_text(
            json.dumps(
                {
                    "content_id": "valid",
                    "content_url": "https://www.zhihu.com/question/1/answer/valid",
                    "title": "2026年民族团结进步宣传周",
                    "content_text": "主题内容",
                    "created_time": "2026-09-20T10:00:00+08:00",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        queue = {"version": 1, "items": {}}

        crawler_runner._update_queue_from_content("zhihu", [raw], queue)

        item = next(iter(queue["items"].values()))
        assert item["visible_comment_count"] == 1
        assert item["comment_count_unknown"] is True
        assert item["queue_signal"] == "zhihu_unknown_comment_count"
    finally:
        _restore(marker, original_update, original_classify)


def test_zhihu_detail_timeout_after_discovery_is_partial_success(tmp_path: Path):
    marker, original_update, original_classify = _install_for_test()
    try:
        stdout = tmp_path / "stdout.log"
        stderr = tmp_path / "stderr.log"
        stdout.write_text(
            "[monitor] ZHIHU_REALTIME_DETAIL_CANDIDATE_TIMEOUT "
            "process_tree_terminated=yes\n",
            encoding="utf-8",
        )
        stderr.write_text("", encoding="utf-8")

        state = crawler_runner._classify_state(
            124,
            stdout,
            stderr,
            content_row_count=144,
            comment_row_count=0,
            comments_enabled=True,
        )
        assert state == "PARTIAL_SUCCESS"
    finally:
        _restore(marker, original_update, original_classify)
