from datetime import datetime
import json
from pathlib import Path

from scripts.backfill_kuaishou_relevant_comments import merge_candidate_files, normalize_and_filter, read_targets


def test_targets_must_be_exactly_fourteen(tmp_path: Path):
    rows = [{"content_id": f"c{i}", "original_url": f"https://x/{i}"} for i in range(14)]
    (tmp_path / "prepared_delivery_tables.json").write_text(json.dumps({"table1": rows}), encoding="utf-8")
    assert len(read_targets(tmp_path)) == 14
    fixed = tmp_path / "targets.json"
    fixed.write_text(json.dumps(rows), encoding="utf-8")
    assert len(read_targets(targets_file=fixed)) == 14


def test_comment_scope_dedupe_and_hierarchy(tmp_path: Path):
    run = tmp_path / "runs" / "01_c0" / "ks" / "jsonl"
    run.mkdir(parents=True)
    rows = [
        {"comment_id": "1", "video_id": "c0", "create_time": 1789956000000, "content": "root", "ip_location": "甘肃"},
        {"comment_id": "2", "video_id": "c0", "create_time": 1789956060000, "content": "reply", "parent_comment_id": "1", "root_comment_id": "1"},
        {"comment_id": "1", "video_id": "c0", "create_time": 1789956000000, "content": "duplicate"},
        {"comment_id": "3", "video_id": "not-target", "create_time": 1789956000000},
    ]
    (run / "detail_comments.jsonl").write_text("".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")
    stats = normalize_and_filter(
        tmp_path, [{"content_id": "c0"}],
        datetime.fromisoformat("2026-09-21T09:00:00+08:00"),
        datetime.fromisoformat("2026-09-21T17:00:00+08:00"),
    )
    assert stats["in_window_comment_count"] == 2
    assert stats["root_comment_count"] == 1
    assert stats["nested_reply_count"] == 1
    assert stats["table4_usable_records"] == 0


def test_merge_deduplicates_comment_ids(tmp_path: Path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir(); new.mkdir()
    (old / "table2_comment_backfill.jsonl").write_text('{"comment_id":"1"}\n', encoding="utf-8")
    (new / "table2_comment_backfill.jsonl").write_text('{"comment_id":"1"}\n{"comment_id":"2"}\n', encoding="utf-8")
    (old / "table4_comment_interaction_backfill.jsonl").write_text("", encoding="utf-8")
    (new / "table4_comment_interaction_backfill.jsonl").write_text("", encoding="utf-8")
    result = merge_candidate_files(old, new)
    assert result == {"merged_table2_records": 2, "merged_table4_records": 0}


def test_merge_prefers_previous_final_merged_file(tmp_path: Path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir(); new.mkdir()
    (old / "table2_comment_backfill.jsonl").write_text("", encoding="utf-8")
    (old / "final_merged_table2_comment_candidates.jsonl").write_text('{"comment_id":"kept"}\n', encoding="utf-8")
    (old / "final_merged_table4_comment_interactions.jsonl").write_text("", encoding="utf-8")
    (new / "table2_comment_backfill.jsonl").write_text("", encoding="utf-8")
    (new / "table4_comment_interaction_backfill.jsonl").write_text("", encoding="utf-8")
    assert merge_candidate_files(old, new)["merged_table2_records"] == 1
